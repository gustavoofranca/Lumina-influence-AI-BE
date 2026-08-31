"""Testes da camada de transporte das integrações: YouTube, Gemini e mídia.

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

import src.integrations.media as media_mod
import src.integrations.youtube as yt_mod
from src.integrations.base import (
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
from src.integrations.media import HttpVideoFetcher, VideoAsset, VideoFetchError
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
                        FakeHttp({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
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
                        FakeHttp({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
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
                        FakeHttp({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        p = YouTubeAdapter().fetch_recent_posts("tok")[0]
    assert (p.likes, p.comments_count, p.reach_total) == (0, 0, 0)
    assert (p.shares, p.saves) == (0, 0)
    assert p.caption is None and p.thumbnail_url is None


def test_youtube_canal_sem_video_nao_chama_a_segunda_rota(app, monkeypatch):
    http = FakeHttp({"/search": FakeResponse(json_body={"items": []})})
    monkeypatch.setattr(yt_mod.requests, "get", http)
    with app.app_context():
        assert YouTubeAdapter().fetch_recent_posts("tok") == []
    assert len(http.calls) == 1


def test_youtube_ignora_resultado_de_busca_sem_id_de_video(app, monkeypatch):
    busca = FakeResponse(json_body={"items": [
        {"id": {"kind": "youtube#channel"}}, {"id": {"videoId": "vid1"}}, {},
    ]})
    http = FakeHttp({"/search": busca,
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
                        FakeHttp({"/search": _busca(["vid1"]), "/videos": _videos([item])}))
    with app.app_context():
        p = YouTubeAdapter().fetch_recent_posts("tok")[0]
    assert (datetime.now(timezone.utc) - p.posted_at).total_seconds() < 60


def test_youtube_erro_na_busca_nao_vira_lista_vazia(app, monkeypatch):
    # Falha de rede lida como "canal sem post" é o padrão "ausência de dado
    # apresentada como zero" — tem que estourar.
    monkeypatch.setattr(yt_mod.requests, "get",
                        FakeHttp({"/search": FakeResponse(status_code=403)}))
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
