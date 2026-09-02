"""Testes da camada de transporte das integrações: Instagram, TikTok, YouTube, Gemini e mídia.

Estes três módulos eram os de menor cobertura da suíte porque todo teste até
aqui os substituía por dublê: `test_integrations.py` usa um `FakeAdapter` e
`test_analysis.py` um cliente falso do Gemini. O que fica sem rede de proteção
é justamente o código que traduz resposta externa em tipo interno — o
mapeamento que produziu o `reach_paid` fixo, o parsing de erro do SDK e a
guarda de tamanho do download.

Nada aqui toca a rede: `requests` e o SDK do Gemini são substituídos por
dublês que devolvem exatamente os payloads que as APIs reais devolvem.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

import src.integrations.instagram as ig_mod
import src.integrations.media as media_mod
import src.integrations.tiktok as tt_mod
import src.integrations.youtube as yt_mod
from src.integrations.base import (
    AccountNotLinkedError,
    PlatformNotConfiguredError,
    PrivateAccountError,
    RateLimitError,
    SocialApiError,
    TokenRevokedError,
)
from src.integrations.gemini import (
    GeminiClient,
    GeminiError,
    GeminiNotConfiguredError,
    GeminiQuotaError,
)
from src.integrations.instagram import InstagramAdapter
from src.integrations.media import HttpVideoFetcher, VideoAsset, VideoFetchError
from src.integrations.tiktok import TikTokAdapter
from src.integrations.youtube import YouTubeAdapter
from src.models import PostType


# ==========================================================================
# Dublês de HTTP
# ==========================================================================
class FakeResponse:
    def __init__(self, *, status_code=200, json_body=None, text=None, headers=None,
                 chunks=None):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text if text is not None else ""
        self.headers = headers or {}
        self._chunks = chunks or []

    def json(self):
        return self._json

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)


class FakeHttp:
    """Roteia GET/POST por trecho da URL e registra as chamadas feitas."""

    def __init__(self, rotas):
        self.rotas = rotas
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for trecho, resp in self.rotas.items():
            if trecho in url:
                return resp
        raise AssertionError(f"URL inesperada no teste: {url}")


# ==========================================================================
# YouTube — credenciais e URL de autorização
# ==========================================================================
def test_youtube_sem_credencial_recusa_antes_de_chamar_a_rede(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "GOOGLE_CLIENT_ID", None)
        monkeypatch.setitem(app.config, "YOUTUBE_CLIENT_ID", None)
        adapter = YouTubeAdapter()
        with pytest.raises(PlatformNotConfiguredError):
            adapter.build_auth_url(state="s", redirect_uri="http://localhost/cb")


def test_youtube_prefere_a_credencial_propria_sobre_a_do_google(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "YOUTUBE_CLIENT_ID", "yt-id")
        monkeypatch.setitem(app.config, "YOUTUBE_CLIENT_SECRET", "yt-secret")
        adapter = YouTubeAdapter()
        assert "client_id=yt-id" in adapter.build_auth_url(state="s", redirect_uri="http://cb")


def test_youtube_pede_consentimento_offline_para_receber_refresh_token(app):
    with app.app_context():
        url = YouTubeAdapter().build_auth_url(state="s", redirect_uri="http://cb")
        # Sem os dois, o Google devolve só access token e a sincronização
        # agendada morre em uma hora.
        assert "access_type=offline" in url
        assert "prompt=consent" in url


# ==========================================================================
# YouTube — troca e renovação de token
# ==========================================================================
def test_youtube_troca_codigo_por_token_com_validade(app, monkeypatch):
    resp = FakeResponse(json_body={
        "access_token": "acc-1", "refresh_token": "ref-1", "expires_in": 3600,
    })
    http = FakeHttp({"oauth2.googleapis.com/token": resp})
    monkeypatch.setattr(yt_mod.requests, "post", http)
    with app.app_context():
        bundle = YouTubeAdapter().exchange_code(code="c", redirect_uri="http://cb")
    assert bundle.access_token == "acc-1"
    assert bundle.refresh_token == "ref-1"
    assert bundle.expires_at > datetime.now(timezone.utc)


def test_youtube_renovacao_preserva_o_refresh_token_que_o_google_nao_repete(app, monkeypatch):
    # No refresh o Google devolve só o access token; perder o refresh aqui
    # desconectaria a conta na próxima renovação.
    resp = FakeResponse(json_body={"access_token": "acc-2", "expires_in": 3600})
    monkeypatch.setattr(yt_mod.requests, "post", FakeHttp({"token": resp}))
    with app.app_context():
        bundle = YouTubeAdapter().refresh("ref-original")
    assert bundle.access_token == "acc-2"
    assert bundle.refresh_token == "ref-original"


def test_youtube_sem_expires_in_deixa_a_validade_nula(app, monkeypatch):
    resp = FakeResponse(json_body={"access_token": "acc-3"})
    monkeypatch.setattr(yt_mod.requests, "post", FakeHttp({"token": resp}))
    with app.app_context():
        assert YouTubeAdapter().exchange_code(code="c", redirect_uri="http://cb").expires_at is None


@pytest.mark.parametrize(
    "status,body,esperado",
    [
        (429, "", RateLimitError),
        (401, '{"error":"invalid_grant"}', TokenRevokedError),
        (401, "sem corpo json", TokenRevokedError),
        (400, '{"error":"invalid_client"}', PlatformNotConfiguredError),
        (403, "", PrivateAccountError),
        (500, "", SocialApiError),
    ],
)
def test_youtube_traduz_erro_http_em_excecao_tipada(app, monkeypatch, status, body, esperado):
    resp = FakeResponse(status_code=status, text=body)
    monkeypatch.setattr(yt_mod.requests, "post", FakeHttp({"token": resp}))
    with app.app_context():
        with pytest.raises(esperado):
            YouTubeAdapter().exchange_code(code="c", redirect_uri="http://cb")


# ==========================================================================
# YouTube — perfil
# ==========================================================================
def test_youtube_le_inscritos_e_identidade_do_canal(app, monkeypatch):
    resp = FakeResponse(json_body={"items": [{
        "id": "UC123",
        "snippet": {"title": "Canal da Ana"},
        "statistics": {"subscriberCount": "1520"},
    }]})
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({"/channels": resp}))
    with app.app_context():
        m = YouTubeAdapter().fetch_profile_metrics("tok")
    assert m.follower_count == 1520
    assert m.handle == "Canal da Ana"
    assert m.platform_user_id == "UC123"


def test_youtube_canal_sem_item_nao_inventa_seguidor(app, monkeypatch):
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({"/channels": FakeResponse(json_body={})}))
    with app.app_context():
        m = YouTubeAdapter().fetch_profile_metrics("tok")
    assert m.follower_count == 0
    assert m.handle is None


# ==========================================================================
# YouTube — normalização de post (é aqui que mora o mapeamento do escopo)
# ==========================================================================
def _busca(ids):
    return FakeResponse(json_body={"items": [{"id": {"videoId": i}} for i in ids]})


def _videos(items):
    return FakeResponse(json_body={"items": items})


def _analytics_indisponivel():
    """Analytics recusando — o caso comum em canal sem relatório de proprietário.

    Entra em toda rota de coleta de propósito: a retenção é best-effort, e os
    testes de normalização precisam continuar medindo o que mediam. Quem quer
    exercitar a retenção usa `_analytics(...)`.
    """
    return FakeResponse(status_code=403, text="{}")


def _analytics(linhas):
    """Resposta da Analytics API. `linhas` = [(video_id, duração_s, pct)]."""
    return FakeResponse(json_body={
        "columnHeaders": [
            {"name": "video"},
            {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
        ],
        "rows": [list(linha) for linha in linhas],
    })


def _coleta(rotas):
    """Rotas de coleta com a Analytics recusando por padrão."""
    return FakeHttp({"youtubeanalytics": _analytics_indisponivel(), **rotas})


def test_youtube_normaliza_video_em_post(app, monkeypatch):
    item = {
        "id": "vid1",
        "snippet": {
            "title": "Rotina de skincare",
            "publishedAt": "2026-08-01T10:30:00Z",
            "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/vid1/hq.jpg"}},
        },
        "statistics": {"viewCount": "4000", "likeCount": "310", "commentCount": "27"},
    }
    monkeypatch.setattr(yt_mod.requests, "get",
                        _coleta({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        posts = YouTubeAdapter().fetch_recent_posts("tok")
    assert len(posts) == 1
    p = posts[0]
    assert p.platform_post_id == "vid1"
    assert p.post_type == PostType.VIDEO
    assert p.caption == "Rotina de skincare"
    assert p.video_url == "https://youtube.com/watch?v=vid1"
    assert p.thumbnail_url == "https://i.ytimg.com/vi/vid1/hq.jpg"
    assert p.posted_at == datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc)
    assert (p.likes, p.comments_count) == (310, 27)


def test_youtube_declara_todo_alcance_como_organico(app, monkeypatch):
    # Contrato da ADR-005: a Data API v3 não separa origem paga, então a
    # divisão é orgânico=total e pago=0 — e isso precisa ser dito ao apresentar
    # o dado. Se algum dia virar estimativa, este teste é quem avisa.
    item = {"id": "vid1", "snippet": {}, "statistics": {"viewCount": "4000"}}
    monkeypatch.setattr(yt_mod.requests, "get",
                        _coleta({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        p = YouTubeAdapter().fetch_recent_posts("tok")[0]
    assert p.reach_total == 4000
    assert p.reach_organic == 4000
    assert p.reach_paid == 0
    assert p.impressions == 4000


def test_youtube_estatistica_ausente_vira_zero_e_nao_quebra(app, monkeypatch):
    # Vídeo com contagem de like desativada não traz `likeCount` no payload; a
    # coluna é NOT NULL e soma sem amostra é zero de verdade (ADR-003).
    item = {"id": "vid1", "snippet": {}, "statistics": {}}
    monkeypatch.setattr(yt_mod.requests, "get",
                        _coleta({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        p = YouTubeAdapter().fetch_recent_posts("tok")[0]
    assert (p.likes, p.comments_count, p.reach_total) == (0, 0, 0)
    assert (p.shares, p.saves) == (0, 0)
    assert p.caption is None and p.thumbnail_url is None


def test_youtube_canal_sem_video_nao_chama_a_segunda_rota(app, monkeypatch):
    http = _coleta({"/search": FakeResponse(json_body={"items": []})})
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        assert YouTubeAdapter().fetch_recent_posts("tok") == []
    assert len(http.calls) == 1


def test_youtube_ignora_resultado_de_busca_sem_id_de_video(app, monkeypatch):
    busca = FakeResponse(json_body={"items": [
        {"id": {"kind": "youtube#channel"}}, {"id": {"videoId": "vid1"}}, {},
    ]})
    http = _coleta({"/search": busca,
                     "/videos": _videos([{"id": "vid1", "snippet": {}, "statistics": {}}])})
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        posts = YouTubeAdapter().fetch_recent_posts("tok")
    assert [p.platform_post_id for p in posts] == ["vid1"]
    assert http.calls[1][1]["params"]["id"] == "vid1"


def test_youtube_data_ilegivel_nao_derruba_a_coleta(app, monkeypatch):
    # `posted_at` é NOT NULL: data quebrada vira "agora" em vez de exceção,
    # porque perder o post inteiro por causa do carimbo é pior.
    item = {"id": "vid1", "snippet": {"publishedAt": "ontem"}, "statistics": {}}
    monkeypatch.setattr(yt_mod.requests, "get",
                        _coleta({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        p = YouTubeAdapter().fetch_recent_posts("tok")[0]
    assert (datetime.now(timezone.utc) - p.posted_at).total_seconds() < 60


def test_youtube_erro_na_busca_nao_vira_lista_vazia(app, monkeypatch):
    # Falha de rede lida como "canal sem post" é o padrão "ausência de dado
    # apresentada como zero" — tem que estourar.
    monkeypatch.setattr(yt_mod.requests, "get",
                        _coleta({"/search": FakeResponse(status_code=403)}))
    with app.app_context():
        with pytest.raises(PrivateAccountError):
            YouTubeAdapter().fetch_recent_posts("tok")


# ==========================================================================
# YouTube — comentários
# ==========================================================================
def test_youtube_normaliza_comentario(app, monkeypatch):
    resp = FakeResponse(json_body={"items": [{
        "id": "c1",
        "snippet": {"topLevelComment": {"snippet": {
            "textDisplay": "amei o vídeo",
            "authorDisplayName": "@maria",
            "publishedAt": "2026-08-02T12:00:00Z",
            "likeCount": 4,
        }}},
    }]})
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({"/commentThreads": resp}))
    with app.app_context():
        c = YouTubeAdapter().fetch_post_comments("tok", "vid1")[0]
    assert (c.platform_comment_id, c.content, c.author_handle) == ("c1", "amei o vídeo", "@maria")
    assert c.like_count == 4


def test_youtube_comentario_sem_snippet_vira_conteudo_vazio(app, monkeypatch):
    resp = FakeResponse(json_body={"items": [{"id": "c1", "snippet": {}}]})
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({"/commentThreads": resp}))
    with app.app_context():
        c = YouTubeAdapter().fetch_post_comments("tok", "vid1")[0]
    assert c.content == ""
    assert c.like_count == 0


def test_youtube_insights_de_post_ainda_nao_medidos(app):
    # A separação detalhada viria da Analytics API; hoje é dicionário vazio e
    # não um número inventado.
    with app.app_context():
        assert YouTubeAdapter().fetch_post_insights("tok", "vid1") == {}


# ==========================================================================
# Gemini — dublê do SDK
# ==========================================================================
class FakeUsage:
    def __init__(self, total):
        self.total_token_count = total


class FakeGenResponse:
    def __init__(self, text, tokens=None):
        self.text = text
        if tokens is not None:
            self.usage_metadata = FakeUsage(tokens)


class FakeFile:
    def __init__(self, name="files/abc", state="ACTIVE"):
        self.name = name
        self.state = state


class FakeModels:
    def __init__(self, resposta=None, erro=None):
        self._resposta = resposta
        self._erro = erro
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._erro is not None:
            raise self._erro
        return self._resposta


class FakeFiles:
    def __init__(self, estados=None, erro_no_delete=False):
        self._estados = list(estados or ["ACTIVE"])
        self._erro_no_delete = erro_no_delete
        self.deleted = []

    def upload(self, *, file):
        return FakeFile(state=self._estados.pop(0))

    def get(self, *, name):
        return FakeFile(name=name, state=self._estados.pop(0))

    def delete(self, *, name):
        self.deleted.append(name)
        if self._erro_no_delete:
            raise RuntimeError("arquivo já removido")


class FakeSdkClient:
    def __init__(self, models=None, files=None):
        self.models = models or FakeModels()
        self.files = files or FakeFiles()


def _cliente(app, monkeypatch, *, models=None, files=None):
    """GeminiClient real com o SDK substituído pelo dublê."""
    with app.app_context():
        client = GeminiClient(api_key="chave-de-teste", model="gemini-3.6-flash")
    client._client = FakeSdkClient(models=models, files=files)
    return client


def _client_error(status):
    from google.genai import errors as genai_errors

    return genai_errors.ClientError(status, {"error": {"message": "boom", "code": status}})


def _server_error():
    from google.genai import errors as genai_errors

    return genai_errors.ServerError(503, {"error": {"message": "indisponível", "code": 503}})


# ==========================================================================
# Gemini — configuração e caminho feliz
# ==========================================================================
def test_gemini_sem_chave_recusa_na_construcao(app):
    # TestConfig zera a GEMINI_API_KEY de propósito: nenhum teste pode gastar
    # cota real.
    with app.app_context():
        with pytest.raises(GeminiNotConfiguredError) as exc:
            GeminiClient()
    assert exc.value.details["missing"] == ["GEMINI_API_KEY"]


def test_gemini_devolve_texto_e_tokens(app, monkeypatch):
    models = FakeModels(resposta=FakeGenResponse('{"ok": true}', tokens=873))
    result = _cliente(app, monkeypatch, models=models).generate_json("analise isto")
    assert result.text == '{"ok": true}'
    assert result.total_tokens == 873
    assert result.model == "gemini-3.6-flash"


def test_gemini_pede_json_e_leva_o_timeout_configurado(app, monkeypatch):
    models = FakeModels(resposta=FakeGenResponse("{}", tokens=1))
    _cliente(app, monkeypatch, models=models).generate_json("p")
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    # O SDK conta em milissegundos; mandar segundos daria timeout de 90ms e
    # toda análise real (~50s contra o Supabase) morreria antes de responder.
    segundos = app.config["GEMINI_TIMEOUT_SECONDS"]
    assert config.http_options.timeout == segundos * 1000


def test_gemini_sem_metadado_de_uso_contabiliza_zero(app, monkeypatch):
    models = FakeModels(resposta=FakeGenResponse("{}"))
    assert _cliente(app, monkeypatch, models=models).generate_json("p").total_tokens == 0


def test_gemini_contagem_nula_de_token_nao_vira_none(app, monkeypatch):
    models = FakeModels(resposta=FakeGenResponse("{}", tokens=None))
    resp = FakeGenResponse("{}")
    resp.usage_metadata = FakeUsage(None)
    models._resposta = resp
    assert _cliente(app, monkeypatch, models=models).generate_json("p").total_tokens == 0


@pytest.mark.parametrize("texto", ["", "   ", None])
def test_gemini_resposta_vazia_e_erro_e_nao_analise_em_branco(app, monkeypatch, texto):
    models = FakeModels(resposta=FakeGenResponse(texto))
    with pytest.raises(GeminiError):
        _cliente(app, monkeypatch, models=models).generate_json("p")


# ==========================================================================
# Gemini — tradução de erro do SDK
# ==========================================================================
def test_gemini_429_vira_erro_de_cota(app, monkeypatch):
    # É o erro mais provável na demonstração: o free tier dá 20 requisições por
    # dia. Precisa chegar ao usuário como 429, não como falha genérica.
    models = FakeModels(erro=_client_error(429))
    with pytest.raises(GeminiQuotaError) as exc:
        _cliente(app, monkeypatch, models=models).generate_json("p")
    assert exc.value.status_code == 429


def test_gemini_400_vira_erro_de_requisicao_com_o_status(app, monkeypatch):
    models = FakeModels(erro=_client_error(400))
    with pytest.raises(GeminiError) as exc:
        _cliente(app, monkeypatch, models=models).generate_json("p")
    assert not isinstance(exc.value, GeminiQuotaError)
    assert exc.value.details["status"] == 400


def test_gemini_5xx_vira_erro_de_indisponibilidade(app, monkeypatch):
    models = FakeModels(erro=_server_error())
    with pytest.raises(GeminiError):
        _cliente(app, monkeypatch, models=models).generate_json("p")


def test_gemini_timeout_de_rede_nao_escapa_como_excecao_crua(app, monkeypatch):
    models = FakeModels(erro=TimeoutError("estourou os 90s"))
    with pytest.raises(GeminiError) as exc:
        _cliente(app, monkeypatch, models=models).generate_json("p")
    assert "estourou" in exc.value.details["msg"]


def test_gemini_mensagem_de_erro_e_truncada(app, monkeypatch):
    models = FakeModels(erro=TimeoutError("x" * 5000))
    with pytest.raises(GeminiError) as exc:
        _cliente(app, monkeypatch, models=models).generate_json("p")
    assert len(exc.value.details["msg"]) <= 300


# ==========================================================================
# Gemini — multimodal
# ==========================================================================
@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """A espera pelo processamento do vídeo dorme 1s por tentativa."""
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_gemini_multimodal_espera_o_video_ficar_ativo(app, monkeypatch):
    files = FakeFiles(estados=["PROCESSING", "PROCESSING", "ACTIVE"])
    models = FakeModels(resposta=FakeGenResponse('{"transcript": "oi"}', tokens=500))
    client = _cliente(app, monkeypatch, models=models, files=files)
    result = client.generate_json_with_video("p", "/tmp/v.mp4")
    assert result.text == '{"transcript": "oi"}'
    assert result.total_tokens == 500
    # O vídeo entra antes do prompt: o modelo lê a instrução já com a mídia.
    assert models.calls[0]["contents"][1] == "p"


def test_gemini_multimodal_falha_de_processamento_vira_erro(app, monkeypatch):
    files = FakeFiles(estados=["FAILED"])
    client = _cliente(app, monkeypatch, files=files)
    with pytest.raises(GeminiError):
        client.generate_json_with_video("p", "/tmp/v.mp4")


def test_gemini_multimodal_sempre_remove_o_arquivo_remoto(app, monkeypatch):
    # A Files API guarda o vídeo por 48h e conta na cota de armazenamento;
    # o descarte precisa acontecer inclusive quando a geração falha.
    files = FakeFiles(estados=["ACTIVE"])
    models = FakeModels(erro=_client_error(400))
    client = _cliente(app, monkeypatch, models=models, files=files)
    with pytest.raises(GeminiError):
        client.generate_json_with_video("p", "/tmp/v.mp4")
    assert files.deleted == ["files/abc"]


def test_gemini_multimodal_429_vira_erro_de_cota(app, monkeypatch):
    files = FakeFiles(estados=["ACTIVE"])
    client = _cliente(app, monkeypatch, models=FakeModels(erro=_client_error(429)), files=files)
    with pytest.raises(GeminiQuotaError):
        client.generate_json_with_video("p", "/tmp/v.mp4")


def test_gemini_falha_ao_limpar_o_arquivo_nao_derruba_a_analise(app, monkeypatch, caplog):
    files = FakeFiles(estados=["ACTIVE"], erro_no_delete=True)
    models = FakeModels(resposta=FakeGenResponse("{}", tokens=10))
    client = _cliente(app, monkeypatch, models=models, files=files)
    with caplog.at_level("WARNING"):
        assert client.generate_json_with_video("p", "/tmp/v.mp4").text == "{}"
    assert "Falha ao remover arquivo" in caplog.text


def test_gemini_multimodal_resposta_vazia_e_erro(app, monkeypatch):
    files = FakeFiles(estados=["ACTIVE"])
    models = FakeModels(resposta=FakeGenResponse("  "))
    client = _cliente(app, monkeypatch, models=models, files=files)
    with pytest.raises(GeminiError):
        client.generate_json_with_video("p", "/tmp/v.mp4")


def test_gemini_upload_quebrado_vira_erro_tipado(app, monkeypatch):
    client = _cliente(app, monkeypatch)
    monkeypatch.setattr(client._client.files, "upload",
                        lambda **_kw: (_ for _ in ()).throw(OSError("arquivo sumiu")))
    with pytest.raises(GeminiError) as exc:
        client.generate_json_with_video("p", "/tmp/v.mp4")
    assert "arquivo sumiu" in exc.value.details["msg"]


# ==========================================================================
# Mídia — download do vídeo
# ==========================================================================
def test_midia_post_sem_video_url_recusa_sem_baixar(app):
    with pytest.raises(VideoFetchError):
        HttpVideoFetcher().fetch(None)


def test_midia_falha_de_rede_vira_erro_tipado(monkeypatch):
    def _explode(*_a, **_kw):
        raise media_mod.requests.RequestException("conexão recusada")

    monkeypatch.setattr(media_mod.requests, "get", _explode)
    with pytest.raises(VideoFetchError) as exc:
        HttpVideoFetcher().fetch("https://cdn.example/v.mp4")
    assert "conexão recusada" in exc.value.details["err"]


def test_midia_status_de_erro_carrega_o_codigo_no_detalhe(monkeypatch):
    monkeypatch.setattr(media_mod.requests, "get",
                        FakeHttp({"cdn": FakeResponse(status_code=404)}))
    with pytest.raises(VideoFetchError) as exc:
        HttpVideoFetcher().fetch("https://cdn.example/v.mp4")
    assert exc.value.details["status"] == 404


def test_midia_baixa_para_arquivo_temporario(monkeypatch):
    resp = FakeResponse(headers={"Content-Type": "video/mp4"}, chunks=[b"abc", b"def"])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"cdn": resp}))
    fetcher = HttpVideoFetcher()
    asset = fetcher.fetch("https://cdn.example/v.mp4")
    try:
        assert asset.mime_type == "video/mp4"
        assert asset.path.endswith(".mp4")
        with open(asset.path, "rb") as fh:
            assert fh.read() == b"abcdef"
    finally:
        fetcher.cleanup(asset)


def test_midia_content_type_com_charset_nao_polui_o_mime(monkeypatch):
    resp = FakeResponse(headers={"Content-Type": "video/quicktime; charset=binary"},
                        chunks=[b"x"])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"cdn": resp}))
    fetcher = HttpVideoFetcher()
    asset = fetcher.fetch("https://cdn.example/v.mov")
    try:
        assert asset.mime_type == "video/quicktime"
        assert asset.path.endswith(".mov")
    finally:
        fetcher.cleanup(asset)


@pytest.mark.parametrize(
    "mime,url,sufixo",
    [
        ("video/webm", "https://cdn.example/v", ".webm"),
        ("application/octet-stream", "https://cdn.example/CLIP.WEBM", ".webm"),
        ("application/octet-stream", "https://cdn.example/v?token=1", ".mp4"),
    ],
)
def test_midia_escolhe_a_extensao_pelo_mime_e_depois_pela_url(monkeypatch, mime, url, sufixo):
    resp = FakeResponse(headers={"Content-Type": mime}, chunks=[b"x"])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"cdn": resp}))
    fetcher = HttpVideoFetcher()
    asset = fetcher.fetch(url)
    try:
        assert asset.path.endswith(sufixo)
    finally:
        fetcher.cleanup(asset)


def test_midia_video_grande_e_interrompido_e_o_temporario_removido(monkeypatch):
    # A guarda existe pra não encher o disco do servidor; se o arquivo parcial
    # ficasse pra trás, o efeito seria o mesmo, só mais devagar.
    monkeypatch.setattr(media_mod, "MAX_BYTES", 10)
    resp = FakeResponse(headers={"Content-Type": "video/mp4"}, chunks=[b"x" * 8, b"y" * 8])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"cdn": resp}))
    antes = set(os.listdir(media_mod.tempfile.gettempdir()))
    with pytest.raises(VideoFetchError):
        HttpVideoFetcher().fetch("https://cdn.example/v.mp4")
    depois = set(os.listdir(media_mod.tempfile.gettempdir()))
    assert not [n for n in depois - antes if n.startswith("lumina_vid_")]


def test_midia_cleanup_e_idempotente(tmp_path):
    caminho = tmp_path / "v.mp4"
    caminho.write_bytes(b"x")
    asset = VideoAsset(path=str(caminho), mime_type="video/mp4")
    fetcher = HttpVideoFetcher()
    fetcher.cleanup(asset)
    assert not caminho.exists()
    fetcher.cleanup(asset)   # segunda passada não pode estourar
    fetcher.cleanup(None)


def test_midia_cleanup_com_arquivo_travado_nao_estoura(monkeypatch, tmp_path):
    # Falhar ao limpar o temporário não pode derrubar a análise que já rodou.
    caminho = tmp_path / "v.mp4"
    caminho.write_bytes(b"x")
    monkeypatch.setattr(media_mod.os, "remove",
                        lambda _p: (_ for _ in ()).throw(OSError("em uso")))
    HttpVideoFetcher().cleanup(VideoAsset(path=str(caminho), mime_type="video/mp4"))


def test_gemini_expoe_o_modelo_que_atendeu(app, monkeypatch):
    # O modelo vai gravado na análise: trocar de versão precisa ficar rastreável.
    assert _cliente(app, monkeypatch).model == "gemini-3.6-flash"


# ==========================================================================
# OAuth de login — Google e Microsoft
# ==========================================================================
# O nível de rota já é coberto em `test_auth.py`, que substitui
# `exchange_code`/`fetch_user_info` por dublê. O que fica descoberto — e é o
# caminho mais crítico do produto, o login — é o transporte destes dois
# clientes: o que eles fazem com resposta fora do feliz.
def _sem_credencial(app, monkeypatch, chaves):
    for chave in chaves:
        monkeypatch.setitem(app.config, chave, None)


def test_google_sem_credencial_recusa_na_construcao(app, monkeypatch):
    from src.integrations.google_oauth import GoogleOAuthClient, GoogleOAuthError

    with app.app_context():
        _sem_credencial(app, monkeypatch, ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"])
        with pytest.raises(GoogleOAuthError):
            GoogleOAuthClient()


def test_microsoft_sem_credencial_recusa_na_construcao(app, monkeypatch):
    from src.integrations.microsoft_oauth import MicrosoftOAuthClient, MicrosoftOAuthError

    with app.app_context():
        _sem_credencial(app, monkeypatch, ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"])
        with pytest.raises(MicrosoftOAuthError):
            MicrosoftOAuthClient()


def test_google_url_de_login_pede_consentimento_offline(app):
    from src.integrations.google_oauth import GoogleOAuthClient

    with app.app_context():
        url = GoogleOAuthClient().build_auth_url(state="s1", redirect_uri="http://localhost/cb")
    assert "state=s1" in url and "response_type=code" in url
    assert "access_type=offline" in url and "include_granted_scopes=true" in url
    assert "scope=openid+email+profile" in url


def test_microsoft_url_de_login_pede_o_escopo_do_graph(app):
    from src.integrations.microsoft_oauth import MicrosoftOAuthClient

    with app.app_context():
        url = MicrosoftOAuthClient().build_auth_url(state="s1", redirect_uri="http://localhost/cb")
    # Sem User.Read o Graph /me devolve 403 e o login termina sem identidade.
    assert "User.Read" in url
    assert "response_mode=query" in url


def test_google_code_rejeitado_carrega_status_e_corpo(app, monkeypatch):
    import src.integrations.google_oauth as goog

    resp = FakeResponse(status_code=400, text='{"error":"invalid_grant"}')
    monkeypatch.setattr(goog.requests, "post", FakeHttp({"token": resp}))
    with app.app_context():
        with pytest.raises(goog.GoogleOAuthError) as exc:
            goog.GoogleOAuthClient().exchange_code(code="c", redirect_uri="http://cb")
    assert exc.value.details["status"] == 400
    assert "invalid_grant" in exc.value.details["body"]


def test_google_rede_fora_vira_erro_tipado_e_nao_500(app, monkeypatch):
    import src.integrations.google_oauth as goog

    def _explode(*_a, **_kw):
        raise goog.requests.RequestException("DNS falhou")

    monkeypatch.setattr(goog.requests, "post", _explode)
    with app.app_context():
        with pytest.raises(goog.GoogleOAuthError):
            goog.GoogleOAuthClient().exchange_code(code="c", redirect_uri="http://cb")


def test_google_userinfo_normaliza_identidade(app, monkeypatch):
    import src.integrations.google_oauth as goog

    resp = FakeResponse(json_body={
        "sub": "1122", "email": "ana@exemplo.com", "name": "Ana Paula",
        "picture": "https://lh3.google/foto.jpg",
    })
    monkeypatch.setattr(goog.requests, "get", FakeHttp({"userinfo": resp}))
    with app.app_context():
        info = goog.GoogleOAuthClient().fetch_user_info("tok")
    assert (info.provider, info.oauth_id, info.email) == ("google", "1122", "ana@exemplo.com")
    assert info.name == "Ana Paula"
    assert info.avatar_url == "https://lh3.google/foto.jpg"


def test_google_sem_nome_cai_no_local_do_email(app, monkeypatch):
    import src.integrations.google_oauth as goog

    resp = FakeResponse(json_body={"sub": "1122", "email": "ana@exemplo.com"})
    monkeypatch.setattr(goog.requests, "get", FakeHttp({"userinfo": resp}))
    with app.app_context():
        info = goog.GoogleOAuthClient().fetch_user_info("tok")
    assert info.name == "ana"
    assert info.avatar_url is None


def test_google_userinfo_com_erro_vira_erro_tipado(app, monkeypatch):
    import src.integrations.google_oauth as goog

    monkeypatch.setattr(goog.requests, "get",
                        FakeHttp({"userinfo": FakeResponse(status_code=401, text="expired")}))
    with app.app_context():
        with pytest.raises(goog.GoogleOAuthError) as exc:
            goog.GoogleOAuthClient().fetch_user_info("tok")
    assert exc.value.details["status"] == 401


@pytest.mark.parametrize("payload", [{"email": "ana@exemplo.com"}, {"sub": "1122"}, {}])
def test_google_userinfo_incompleto_vira_erro_tipado_e_nao_keyerror(app, monkeypatch, payload):
    # Um userinfo sem `sub` ou sem `email` é resposta possível — basta o usuário
    # não conceder o escopo. Sem tratamento vira KeyError e o login responde 500
    # em vez do 502 que descreve o que aconteceu. O cliente da Microsoft já
    # tratava o caso equivalente.
    import src.integrations.google_oauth as goog

    monkeypatch.setattr(goog.requests, "get", FakeHttp({"userinfo": FakeResponse(json_body=payload)}))
    with app.app_context():
        with pytest.raises(goog.GoogleOAuthError):
            goog.GoogleOAuthClient().fetch_user_info("tok")


def test_microsoft_prefere_mail_sobre_principal_name(app, monkeypatch):
    import src.integrations.microsoft_oauth as ms

    resp = FakeResponse(json_body={
        "id": "aaa", "mail": "ana@empresa.com",
        "userPrincipalName": "ana_empresa.com#EXT#@tenant.onmicrosoft.com",
        "displayName": "Ana Paula",
    })
    monkeypatch.setattr(ms.requests, "get", FakeHttp({"graph.microsoft.com": resp}))
    with app.app_context():
        info = ms.MicrosoftOAuthClient().fetch_user_info("tok")
    # O userPrincipalName de conta convidada não é endereço de e-mail válido.
    assert info.email == "ana@empresa.com"
    assert info.name == "Ana Paula"


def test_microsoft_sem_mail_usa_o_principal_name(app, monkeypatch):
    import src.integrations.microsoft_oauth as ms

    resp = FakeResponse(json_body={"id": "aaa", "userPrincipalName": "ana@empresa.com"})
    monkeypatch.setattr(ms.requests, "get", FakeHttp({"graph.microsoft.com": resp}))
    with app.app_context():
        info = ms.MicrosoftOAuthClient().fetch_user_info("tok")
    assert info.email == "ana@empresa.com"
    assert info.name == "ana"


def test_microsoft_conta_sem_email_vira_erro_tipado(app, monkeypatch):
    import src.integrations.microsoft_oauth as ms

    resp = FakeResponse(json_body={"id": "aaa", "displayName": "Ana"})
    monkeypatch.setattr(ms.requests, "get", FakeHttp({"graph.microsoft.com": resp}))
    with app.app_context():
        with pytest.raises(ms.MicrosoftOAuthError) as exc:
            ms.MicrosoftOAuthClient().fetch_user_info("tok")
    assert "data_keys" in exc.value.details


def test_microsoft_code_rejeitado_vira_erro_tipado(app, monkeypatch):
    import src.integrations.microsoft_oauth as ms

    monkeypatch.setattr(ms.requests, "post",
                        FakeHttp({"login.microsoftonline.com": FakeResponse(status_code=400, text="bad")}))
    with app.app_context():
        with pytest.raises(ms.MicrosoftOAuthError) as exc:
            ms.MicrosoftOAuthClient().exchange_code(code="c", redirect_uri="http://cb")
    assert exc.value.details["status"] == 400


def test_microsoft_graph_fora_do_ar_vira_erro_tipado(app, monkeypatch):
    import src.integrations.microsoft_oauth as ms

    def _explode(*_a, **_kw):
        raise ms.requests.RequestException("timeout")

    monkeypatch.setattr(ms.requests, "get", _explode)
    with app.app_context():
        with pytest.raises(ms.MicrosoftOAuthError):
            ms.MicrosoftOAuthClient().fetch_user_info("tok")


def test_troca_de_code_bem_sucedida_devolve_o_payload_do_provedor(app, monkeypatch):
    import src.integrations.google_oauth as goog

    corpo = {"access_token": "at", "refresh_token": "rt", "id_token": "it", "expires_in": 3599}
    monkeypatch.setattr(goog.requests, "post", FakeHttp({"token": FakeResponse(json_body=corpo)}))
    with app.app_context():
        assert goog.GoogleOAuthClient().exchange_code(code="c", redirect_uri="http://cb") == corpo


# ==========================================================================
# Instagram — credenciais, escopos e troca de token
# ==========================================================================
IG_ID = "17841400000000000"


def _paginas(*itens):
    return FakeResponse(json_body={"data": list(itens)})


def _pagina(*, id="pg-1", ig_id=IG_ID, token="tok-pagina"):
    p = {"id": id, "name": "Página do Criador"}
    if ig_id is not None:
        p["instagram_business_account"] = {"id": ig_id}
    if token is not None:
        p["access_token"] = token
    return p


def test_instagram_sem_credencial_recusa_antes_de_chamar_a_rede(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "META_CLIENT_ID", None)
        with pytest.raises(PlatformNotConfiguredError):
            InstagramAdapter().build_auth_url(state="s", redirect_uri="http://cb")


def test_instagram_pede_os_quatro_escopos_da_configuracao_com_facebook_login(app):
    with app.app_context():
        url = InstagramAdapter().build_auth_url(state="s", redirect_uri="http://cb")
    # instagram_manage_insights só existe nesta configuração, e sem
    # pages_read_engagement a leitura da Página encontrada volta 403.
    for escopo in ("instagram_basic", "instagram_manage_insights",
                   "pages_show_list", "pages_read_engagement"):
        assert escopo in url


def test_instagram_usa_versao_da_graph_ainda_suportada(app):
    with app.app_context():
        url = InstagramAdapter().build_auth_url(state="s", redirect_uri="http://cb")
    assert ig_mod.API_VERSION in url
    # A v21.0 expira em jan/2027 e é anterior à remoção de `impressions`.
    assert ig_mod.API_VERSION not in ("v21.0", "v20.0")


def test_instagram_troca_codigo_por_long_lived_sem_refresh_token(app, monkeypatch):
    http = FakeHttp({"oauth/access_token": FakeResponse(
        json_body={"access_token": "acc-1", "expires_in": 5183944})})
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        bundle = InstagramAdapter().exchange_code(code="c", redirect_uri="http://cb")
    assert bundle.access_token == "acc-1"
    assert bundle.refresh_token is None  # Meta não emite refresh token
    assert bundle.expires_at > datetime.now(timezone.utc)


def test_instagram_renova_pelo_fb_exchange_token(app, monkeypatch):
    http = FakeHttp({"oauth/access_token": FakeResponse(json_body={"access_token": "acc-2"})})
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        bundle = InstagramAdapter().refresh("antigo")
    assert bundle.access_token == "acc-2"
    assert http.calls[0][1]["params"]["grant_type"] == "fb_exchange_token"


# ==========================================================================
# Instagram — descoberta da conta profissional
# ==========================================================================
def test_instagram_encontra_a_pagina_com_instagram_vinculado(app, monkeypatch):
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina(id="sem-ig", ig_id=None), _pagina()),
        f"/{IG_ID}": FakeResponse(json_body={
            "id": IG_ID, "username": "criador", "followers_count": 4200}),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        perfil = InstagramAdapter().fetch_profile_metrics("token-de-usuario")
    assert perfil.handle == "criador"
    assert perfil.follower_count == 4200
    assert perfil.platform_user_id == IG_ID


def test_instagram_perfil_usa_o_token_da_pagina_e_nao_o_do_usuario(app, monkeypatch):
    # O token que sai do login é de usuário do Facebook; as rotas do Instagram
    # só aceitam o token da Página. Trocar os dois é 403 em produção.
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina()),
        f"/{IG_ID}": FakeResponse(json_body={"id": IG_ID, "username": "c",
                                             "followers_count": 1}),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        InstagramAdapter().fetch_profile_metrics("token-de-usuario")
    url_perfil, kwargs = http.calls[-1]
    assert IG_ID in url_perfil
    assert kwargs["params"]["access_token"] == "tok-pagina"


def test_instagram_nunca_pergunta_o_perfil_ao_no_me(app, monkeypatch):
    # `/me` num token de usuário do Facebook é a pessoa, não o perfil do
    # Instagram: `followers_count` e `media` não existem nesse nó.
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina()),
        f"/{IG_ID}": FakeResponse(json_body={"id": IG_ID, "username": "c",
                                             "followers_count": 1}),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        InstagramAdapter().fetch_profile_metrics("t")
    assert not any(url.endswith("/me") for url, _ in http.calls)


def test_instagram_conta_pessoal_vira_erro_tipado_e_nao_perfil_vazio(app, monkeypatch):
    http = FakeHttp({"/me/accounts": _paginas(_pagina(ig_id=None))})
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        with pytest.raises(AccountNotLinkedError):
            InstagramAdapter().fetch_recent_posts("t")


def test_instagram_sem_nenhuma_pagina_vira_erro_tipado(app, monkeypatch):
    monkeypatch.setattr(ig_mod.requests, "get", FakeHttp({"/me/accounts": _paginas()}))
    with app.app_context():
        with pytest.raises(AccountNotLinkedError):
            InstagramAdapter().fetch_recent_posts("t")


def test_instagram_pagina_sem_token_e_escopo_faltando_e_nao_desvinculo(app, monkeypatch):
    # Os dois casos pedem orientações opostas ao usuário: reconceder permissão
    # versus vincular a conta a uma Página.
    monkeypatch.setattr(ig_mod.requests, "get",
                        FakeHttp({"/me/accounts": _paginas(_pagina(token=None))}))
    with app.app_context():
        with pytest.raises(PlatformNotConfiguredError):
            InstagramAdapter().fetch_recent_posts("t")


def test_instagram_descobre_a_conta_uma_vez_so_por_sync(app, monkeypatch):
    # A mesma instância atende perfil, mídia e comentários de cada post; repetir
    # a descoberta gastaria uma chamada por post do limite da Graph.
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina()),
        f"/{IG_ID}/media": FakeResponse(json_body={"data": []}),
        f"/{IG_ID}": FakeResponse(json_body={"id": IG_ID, "username": "c",
                                             "followers_count": 1}),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        adapter = InstagramAdapter()
        adapter.fetch_profile_metrics("t")
        adapter.fetch_recent_posts("t")
    assert sum(1 for url, _ in http.calls if "/me/accounts" in url) == 1


# ==========================================================================
# Instagram — normalização de mídia
# ==========================================================================
def _insights(**metricas):
    return {"data": [{"name": n, "values": [{"value": v}]} for n, v in metricas.items()]}


def _midia(*itens):
    return FakeResponse(json_body={"data": list(itens)})


def _com_conta(monkeypatch, midia):
    http = FakeHttp({"/me/accounts": _paginas(_pagina()), f"/{IG_ID}/media": midia})
    monkeypatch.setattr(ig_mod.requests, "get", http)
    return http


def test_instagram_pede_views_e_nunca_a_metrica_removida(app, monkeypatch):
    # `impressions` foi removida na v22.0 e devolve erro para mídia posterior a
    # 02/07/2024: pedi-la derruba a coleta inteira, não só a métrica.
    http = _com_conta(monkeypatch, _midia())
    with app.app_context():
        InstagramAdapter().fetch_recent_posts("t")
    campos = http.calls[-1][1]["params"]["fields"]
    assert "views" in campos
    assert "impressions" not in campos


def test_instagram_normaliza_post_com_views_no_lugar_de_impressoes(app, monkeypatch):
    _com_conta(monkeypatch, _midia({
        "id": "m-1", "caption": "olá", "media_type": "IMAGE", "media_product_type": "FEED",
        "timestamp": "2026-08-01T12:00:00+0000", "media_url": "http://img",
        "like_count": 120, "comments_count": 8,
        "insights": _insights(reach=3000, views=4500, saved=30, shares=12),
    }))
    with app.app_context():
        post = InstagramAdapter().fetch_recent_posts("t")[0]
    assert post.post_type is PostType.IMAGE
    assert post.reach_total == 3000
    assert post.impressions == 4500  # `views` alimenta o campo interno
    assert post.likes == 120
    assert post.saves == 30
    assert post.shares == 12
    assert post.video_url is None


def test_instagram_declara_todo_alcance_como_organico(app, monkeypatch):
    # Sem a Marketing API a Graph não separa pago; inventar a divisão aqui seria
    # apresentar estimativa como medição (ADR-005).
    _com_conta(monkeypatch, _midia({
        "id": "m-1", "media_type": "IMAGE", "timestamp": "2026-08-01T12:00:00+0000",
        "insights": _insights(reach=900),
    }))
    with app.app_context():
        post = InstagramAdapter().fetch_recent_posts("t")[0]
    assert post.reach_organic == 900
    assert post.reach_paid == 0


def test_instagram_separa_reel_de_video_de_feed(app, monkeypatch):
    # `media_type` chama os dois de VIDEO; quem distingue é media_product_type,
    # e o benchmarking compara por tipo de post.
    _com_conta(monkeypatch, _midia(
        {"id": "r", "media_type": "VIDEO", "media_product_type": "REELS",
         "timestamp": "2026-08-01T12:00:00+0000", "media_url": "http://v1",
         "insights": _insights(reach=1)},
        {"id": "v", "media_type": "VIDEO", "media_product_type": "FEED",
         "timestamp": "2026-08-01T12:00:00+0000", "media_url": "http://v2",
         "insights": _insights(reach=1)},
    ))
    with app.app_context():
        reel, video = InstagramAdapter().fetch_recent_posts("t")
    assert reel.post_type is PostType.REEL
    assert video.post_type is PostType.VIDEO
    assert reel.video_url == "http://v1"  # o download multimodal depende disso


def test_instagram_carrossel_vira_carousel(app, monkeypatch):
    _com_conta(monkeypatch, _midia({
        "id": "c", "media_type": "CAROUSEL_ALBUM", "media_product_type": "FEED",
        "timestamp": "2026-08-01T12:00:00+0000", "insights": _insights(reach=1),
    }))
    with app.app_context():
        assert InstagramAdapter().fetch_recent_posts("t")[0].post_type is PostType.CAROUSEL


def test_instagram_insight_ausente_nao_quebra_a_coleta(app, monkeypatch):
    # Mídia recém-publicada volta sem insights; o post ainda precisa entrar.
    _com_conta(monkeypatch, _midia({"id": "m", "media_type": "IMAGE"}))
    with app.app_context():
        post = InstagramAdapter().fetch_recent_posts("t")[0]
    assert post.reach_total == 0
    assert post.impressions == 0


def test_instagram_data_ilegivel_nao_derruba_a_coleta(app, monkeypatch):
    _com_conta(monkeypatch, _midia({
        "id": "m", "media_type": "IMAGE", "timestamp": "ontem",
        "insights": _insights(reach=1),
    }))
    with app.app_context():
        assert InstagramAdapter().fetch_recent_posts("t")[0].posted_at is not None


@pytest.mark.parametrize("status, esperado", [
    (429, RateLimitError),
    (401, TokenRevokedError),
    (403, PrivateAccountError),
    (500, SocialApiError),
])
def test_instagram_traduz_erro_http_em_excecao_tipada(app, monkeypatch, status, esperado):
    monkeypatch.setattr(ig_mod.requests, "get",
                        FakeHttp({"/me/accounts": FakeResponse(status_code=status, text="{}")}))
    with app.app_context():
        with pytest.raises(esperado):
            InstagramAdapter().fetch_recent_posts("t")


# ==========================================================================
# Instagram — insights e comentários por post
# ==========================================================================
def test_instagram_insights_de_post_usam_o_token_da_pagina(app, monkeypatch):
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina()),
        "/m-1/insights": FakeResponse(json_body=_insights(reach=10, views=20)),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        dados = InstagramAdapter().fetch_post_insights("t", "m-1")
    assert dados == {"reach": 10, "views": 20}
    assert http.calls[-1][1]["params"]["access_token"] == "tok-pagina"
    assert "impressions" not in http.calls[-1][1]["params"]["metric"]


def test_instagram_normaliza_comentario(app, monkeypatch):
    http = FakeHttp({
        "/me/accounts": _paginas(_pagina()),
        "/m-1/comments": FakeResponse(json_body={"data": [{
            "id": "c-1", "text": "amei", "username": "fa",
            "timestamp": "2026-08-02T10:00:00+0000", "like_count": 3}]}),
    })
    monkeypatch.setattr(ig_mod.requests, "get", http)
    with app.app_context():
        c = InstagramAdapter().fetch_post_comments("t", "m-1")[0]
    assert c.content == "amei"
    assert c.author_handle == "fa"
    assert c.like_count == 3


# ==========================================================================
# TikTok — credenciais e token
# ==========================================================================
def _tiktok_ok(**data):
    return FakeResponse(json_body={"data": data, "error": {"code": "ok", "message": ""}})


def _tiktok_erro(codigo, mensagem="falhou"):
    # O TikTok responde 200 mesmo quando falha: o erro vive no corpo.
    return FakeResponse(json_body={"data": {}, "error": {"code": codigo, "message": mensagem}})


def test_tiktok_sem_credencial_recusa_antes_de_chamar_a_rede(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "TIKTOK_CLIENT_KEY", None)
        with pytest.raises(PlatformNotConfiguredError):
            TikTokAdapter().build_auth_url(state="s", redirect_uri="http://cb")


def test_tiktok_url_de_autorizacao_pede_os_escopos_de_leitura(app):
    with app.app_context():
        url = TikTokAdapter().build_auth_url(state="s", redirect_uri="http://cb")
    for escopo in ("user.info.basic", "user.info.stats", "video.list"):
        assert escopo in url


def test_tiktok_troca_codigo_por_token_com_open_id(app, monkeypatch):
    http = FakeHttp({"oauth/token": FakeResponse(json_body={
        "access_token": "acc", "refresh_token": "ref",
        "expires_in": 86400, "open_id": "open-1"})})
    monkeypatch.setattr(tt_mod.requests, "post", http)
    with app.app_context():
        bundle = TikTokAdapter().exchange_code(code="c", redirect_uri="http://cb")
    assert bundle.access_token == "acc"
    assert bundle.platform_user_id == "open-1"
    assert bundle.expires_at > datetime.now(timezone.utc)


def test_tiktok_renovacao_preserva_o_refresh_token_quando_ele_nao_volta(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "post",
                        FakeHttp({"oauth/token": FakeResponse(json_body={"access_token": "novo"})}))
    with app.app_context():
        bundle = TikTokAdapter().refresh("antigo")
    assert bundle.refresh_token == "antigo"


# ==========================================================================
# TikTok — o erro que chega dentro de uma resposta 200
# ==========================================================================
@pytest.mark.parametrize("codigo, esperado", [
    ("access_token_invalid", TokenRevokedError),
    ("token_expired", TokenRevokedError),
    ("rate_limit_exceeded", RateLimitError),
    ("scope_not_authorized", PlatformNotConfiguredError),
    ("internal_error", SocialApiError),
])
def test_tiktok_erro_no_corpo_de_um_200_vira_excecao_tipada(app, monkeypatch, codigo, esperado):
    # Sem esta leitura, token revogado devolvia lista vazia e a interface diria
    # "criador sem post" — falha externa apresentada como ausência de dado.
    monkeypatch.setattr(tt_mod.requests, "post",
                        FakeHttp({"video/list": _tiktok_erro(codigo)}))
    with app.app_context():
        with pytest.raises(esperado):
            TikTokAdapter().fetch_recent_posts("t")


def test_tiktok_corpo_sem_objeto_de_erro_nao_e_tratado_como_sucesso(app, monkeypatch):
    # Só `code == "ok"` autoriza seguir; formato inesperado é erro, não silêncio.
    monkeypatch.setattr(tt_mod.requests, "get",
                        FakeHttp({"user/info": FakeResponse(json_body={"data": {}})}))
    with app.app_context():
        with pytest.raises(SocialApiError):
            TikTokAdapter().fetch_profile_metrics("t")


# ==========================================================================
# TikTok — perfil e vídeos
# ==========================================================================
def test_tiktok_handle_e_o_arroba_do_perfil_e_nao_o_nome_de_exibicao(app, monkeypatch):
    # O handle entra na chave única (influencer, plataforma, handle): usar o
    # nome de exibição faria uma troca de nome nascer como conta duplicada.
    monkeypatch.setattr(tt_mod.requests, "get", FakeHttp({"user/info": _tiktok_ok(
        user={"open_id": "o-1", "username": "criador.oficial",
              "display_name": "Criador ✨", "follower_count": 8200})}))
    with app.app_context():
        perfil = TikTokAdapter().fetch_profile_metrics("t")
    assert perfil.handle == "criador.oficial"
    assert perfil.follower_count == 8200
    assert perfil.platform_user_id == "o-1"


def test_tiktok_sem_username_cai_no_nome_de_exibicao(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "get", FakeHttp({"user/info": _tiktok_ok(
        user={"open_id": "o-1", "display_name": "Criador", "follower_count": 1})}))
    with app.app_context():
        assert TikTokAdapter().fetch_profile_metrics("t").handle == "Criador"


def test_tiktok_normaliza_video_em_post(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "post", FakeHttp({"video/list": _tiktok_ok(
        videos=[{"id": 998, "title": "trend", "create_time": 1756600000,
                 "cover_image_url": "http://capa", "share_url": "http://tiktok.com/@x/video/998",
                 "view_count": 50000, "like_count": 4000,
                 "comment_count": 120, "share_count": 300}])}))
    with app.app_context():
        post = TikTokAdapter().fetch_recent_posts("t")[0]
    assert post.platform_post_id == "998"  # id numérico vira string
    assert post.post_type is PostType.VIDEO
    assert post.reach_total == post.impressions == 50000
    assert post.likes == 4000
    assert post.shares == 300


def test_tiktok_nao_entrega_pagina_como_se_fosse_arquivo_de_video(app, monkeypatch):
    # `share_url` é a página do TikTok. Gravá-la em `video_url` faria o
    # analisador multimodal baixar HTML e tratá-lo como vídeo.
    monkeypatch.setattr(tt_mod.requests, "post", FakeHttp({"video/list": _tiktok_ok(
        videos=[{"id": 1, "share_url": "http://tiktok.com/@x/video/1", "view_count": 1}])}))
    with app.app_context():
        assert TikTokAdapter().fetch_recent_posts("t")[0].video_url is None


def test_tiktok_declara_todo_alcance_como_organico(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "post", FakeHttp({"video/list": _tiktok_ok(
        videos=[{"id": 1, "view_count": 700}])}))
    with app.app_context():
        post = TikTokAdapter().fetch_recent_posts("t")[0]
    assert post.reach_organic == 700
    assert post.reach_paid == 0


def test_tiktok_video_sem_data_nao_derruba_a_coleta(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "post", FakeHttp({"video/list": _tiktok_ok(
        videos=[{"id": 1, "view_count": 1}])}))
    with app.app_context():
        assert TikTokAdapter().fetch_recent_posts("t")[0].posted_at is not None


def test_tiktok_status_http_de_erro_ainda_vira_excecao_tipada(app, monkeypatch):
    monkeypatch.setattr(tt_mod.requests, "post",
                        FakeHttp({"video/list": FakeResponse(status_code=429, text="{}")}))
    with app.app_context():
        with pytest.raises(RateLimitError):
            TikTokAdapter().fetch_recent_posts("t")


def test_tiktok_declara_o_que_ainda_nao_coleta(app):
    # Insights por post e comentários exigem a Business API. Devolver vazio é a
    # resposta honesta; o teste existe para que a mudança seja deliberada.
    with app.app_context():
        adapter = TikTokAdapter()
        assert adapter.fetch_post_insights("t", "1") == {}
        assert adapter.fetch_post_comments("t", "1") == []


# ==========================================================================
# Mídia — a guarda que impede página virar vídeo
# ==========================================================================
def test_midia_pagina_html_nao_e_aceita_como_video(monkeypatch):
    resp = FakeResponse(headers={"Content-Type": "text/html; charset=utf-8"}, chunks=[b"<html>"])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"tiktok": resp}))
    with pytest.raises(VideoFetchError) as exc:
        HttpVideoFetcher().fetch("https://tiktok.com/@x/video/1")
    assert exc.value.details["mime"] == "text/html"


def test_midia_octet_stream_continua_aceito(monkeypatch):
    # CDN de vídeo costuma servir octet-stream; a guarda é lista de exclusão
    # justamente para não recusar download legítimo.
    resp = FakeResponse(headers={"Content-Type": "application/octet-stream"}, chunks=[b"x"])
    monkeypatch.setattr(media_mod.requests, "get", FakeHttp({"cdn": resp}))
    fetcher = HttpVideoFetcher()
    asset = fetcher.fetch("https://cdn.example/v.mp4")
    try:
        assert asset.path.endswith(".mp4")
    finally:
        fetcher.cleanup(asset)


# ==========================================================================
# YouTube — retenção, da Analytics API
# ==========================================================================
def _item_video(vid="vid1"):
    return {
        "id": vid,
        "snippet": {"title": "Titulo", "publishedAt": "2026-08-01T10:00:00Z",
                    "thumbnails": {"high": {"url": "http://thumb"}}},
        "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
    }


def test_youtube_coleta_tempo_de_exibicao_e_retencao(app, monkeypatch):
    # Os dois campos existiam no modelo e no painel desde a B7 e ninguém os
    # coletava: para a conta real chegavam sempre nulos.
    http = FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": _analytics([("vid1", 132.5, 47.5)]),
    })
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        post = YouTubeAdapter().fetch_recent_posts("t")[0]
    assert post.avg_watch_time == 132.5
    # `averageViewPercentage` vem em 0–100; o campo interno é fração.
    assert post.retention_rate == 0.475


def test_youtube_pede_as_metricas_de_retencao_por_video(app, monkeypatch):
    http = FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": _analytics([("vid1", 10.0, 20.0)]),
    })
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        YouTubeAdapter().fetch_recent_posts("t")
    chamada = next(k for url, k in http.calls if "youtubeanalytics" in url)
    params = chamada["params"]
    assert params["metrics"] == "averageViewDuration,averageViewPercentage"
    # Sem `dimensions=video` a API agrega todos os vídeos numa linha só, e a
    # retenção de um vídeo passaria a ser a média do canal.
    assert params["dimensions"] == "video"
    assert params["filters"] == "video==vid1"
    assert params["ids"] == "channel==MINE"
    # As duas datas são obrigatórias na Analytics API.
    assert params["startDate"] < params["endDate"]


def test_youtube_analytics_recusada_deixa_a_retencao_nula_e_nao_zero(app, monkeypatch):
    # 403 é o caso comum: o token autoriza analytics e o canal não tem
    # relatório de proprietário. Retenção zero afirmaria "ninguém assistiu".
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": FakeResponse(status_code=403, text="{}"),
    }))
    with app.app_context():
        post = YouTubeAdapter().fetch_recent_posts("t")[0]
    assert post.avg_watch_time is None
    assert post.retention_rate is None
    # E o que importa continua vindo: a retenção é enfeite do painel, o
    # alcance é o produto.
    assert post.reach_total == 1000


def test_youtube_analytics_fora_do_ar_nao_derruba_a_coleta(app, monkeypatch):
    def _get(url, **kwargs):
        if "youtubeanalytics" in url:
            raise yt_mod.requests.RequestException("timeout")
        return FakeHttp({"/search": _busca(["vid1"]),
                         "/videos": _videos([_item_video()])})(url, **kwargs)

    monkeypatch.setattr(yt_mod.requests, "get", _get)
    with app.app_context():
        posts = YouTubeAdapter().fetch_recent_posts("t")
    assert len(posts) == 1
    assert posts[0].retention_rate is None


def test_youtube_video_sem_linha_na_analytics_fica_sem_retencao(app, monkeypatch):
    # Vídeo recém-publicado não tem dado ainda: a API omite a linha.
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({
        "/search": _busca(["vid1", "vid2"]),
        "/videos": _videos([_item_video("vid1"), _item_video("vid2")]),
        "youtubeanalytics": _analytics([("vid1", 90.0, 30.0)]),
    }))
    with app.app_context():
        posts = {p.platform_post_id: p for p in YouTubeAdapter().fetch_recent_posts("t")}
    assert posts["vid1"].retention_rate == 0.3
    assert posts["vid2"].retention_rate is None


def test_youtube_le_a_analytics_pela_ordem_das_colunas(app, monkeypatch):
    # Assumir posição fixa quebraria em silêncio se a API acrescentasse coluna
    # — e o erro seria trocar duração por percentual, que passa por plausível.
    corpo = FakeResponse(json_body={
        "columnHeaders": [
            {"name": "averageViewPercentage"},
            {"name": "video"},
            {"name": "averageViewDuration"},
        ],
        "rows": [[60.0, "vid1", 200.0]],
    })
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": corpo,
    }))
    with app.app_context():
        post = YouTubeAdapter().fetch_recent_posts("t")[0]
    assert post.avg_watch_time == 200.0
    assert post.retention_rate == 0.6


def test_youtube_analytics_sem_as_colunas_esperadas_nao_inventa(app, monkeypatch):
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": FakeResponse(json_body={"columnHeaders": [{"name": "outra"}],
                                                    "rows": [["x"]]}),
    }))
    with app.app_context():
        post = YouTubeAdapter().fetch_recent_posts("t")[0]
    assert post.retention_rate is None


def test_youtube_sem_video_nao_chama_a_analytics(app, monkeypatch):
    http = FakeHttp({"/search": FakeResponse(json_body={"items": []})})
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        assert YouTubeAdapter().fetch_recent_posts("t") == []
    assert not any("youtubeanalytics" in url for url, _ in http.calls)


def test_youtube_linha_curta_da_analytics_e_ignorada(app, monkeypatch):
    # Linha com menos colunas que o cabeçalho promete: descartar é o único
    # caminho honesto, porque não se sabe qual valor está faltando.
    corpo = FakeResponse(json_body={
        "columnHeaders": [
            {"name": "video"},
            {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
        ],
        "rows": [["vid1", 10.0]],
    })
    monkeypatch.setattr(yt_mod.requests, "get", FakeHttp({
        "/search": _busca(["vid1"]),
        "/videos": _videos([_item_video()]),
        "youtubeanalytics": corpo,
    }))
    with app.app_context():
        post = YouTubeAdapter().fetch_recent_posts("t")[0]
    assert post.retention_rate is None
    assert post.avg_watch_time is None
