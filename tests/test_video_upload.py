"""Testes do upload de vídeo — a única porta da API que recebe arquivo.

O que estes testes guardam:

1. que o arquivo enviado nunca decide onde grava (travessia de diretório);
2. que o teto de corpo desta rota não vaza para as outras;
3. que o escopo de agência vale aqui como em todo o resto;
4. que falha de análise não deixa lixo — nem post fantasma, nem arquivo órfão.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from src.extensions import db
from src.integrations.base import SocialApiError
from src.models import Post, SentimentLabel
from src.services import video_upload_service

from tests.test_integrations import ctx  # noqa: F401 — fixture reaproveitada


class _AnaliseFalsa:
    """Substitui o Gemini: devolve o JSON que o serviço espera, sem rede."""

    def __init__(self, transcript="Transcricao de teste do video enviado."):
        self.transcript = transcript

    def __call__(self, post, *, agency_id, video_fetcher=None, **kwargs):
        from src.models import AIAnalysis

        # Exercita o fetcher de verdade: é ele que prova que o arquivo gravado
        # é legível. Sem esta chamada, o teste passaria com o disco vazio.
        asset = video_fetcher.fetch(post.video_url)
        assert Path(asset.path).exists()
        video_fetcher.cleanup(asset)
        # E o arquivo continua lá: `cleanup` do LocalFileFetcher é inerte de
        # propósito, porque a mídia é do produto e não temporária.
        assert Path(asset.path).exists(), "cleanup apagou mídia que é do post"

        analise = AIAnalysis(
            post_id=post.id, model_version="fake-multimodal",
            sentiment_score=0.6, sentiment_label=SentimentLabel.POSITIVE,
            script_score=7.0, brand_coherence_score=80.0, bot_probability=5.0,
            transcript_text=self.transcript, key_phrases=["teste"],
        )
        db.session.add(analise)
        db.session.flush()
        return analise


def _enviar(client, contexto, *, conteudo=b"\x00\x01fake-video", nome="clipe.mp4",
            mime="video/mp4", campo="video", extra=None):
    """Monta o multipart como o navegador monta.

    O parâmetro não se chama `ctx` para não sombrear a fixture importada:
    o sombreamento funciona, mas o linter aponta redefinição — com razão.
    """
    dados = {campo: (io.BytesIO(conteudo), nome, mime)}
    dados.update(extra or {})
    return client.post(
        f"/api/v1/influencers/{contexto.inf_id}/video-analysis",
        headers=contexto.h_admin, data=dados, content_type="multipart/form-data",
    )


def test_upload_cria_post_e_analise(client, ctx, app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = _enviar(client, ctx, extra={"caption": "Resenha honesta #publi"})
    assert r.status_code == 201

    corpo = r.get_json()["data"]
    assert corpo["analysis"]["transcript_text"] == "Transcricao de teste do video enviado."

    with app.app_context():
        post = db.session.get(Post, uuid.UUID(corpo["post_id"]))
        assert post.post_type.value == "video"
        assert post.caption == "Resenha honesta #publi"
        # O endereço declara que a mídia é local: quem ler o campo depois não
        # deve sair tentando baixá-la da rede.
        assert post.video_url.startswith("file://storage/videos/")


def test_nome_do_arquivo_nunca_vira_caminho(client, ctx, app, monkeypatch):  # noqa: F811
    """Nome vindo do cliente é texto, não destino.

    `../../` no nome é travessia de diretório esperando acontecer: se o nome
    fosse usado para montar o caminho, este envio escreveria fora de `storage/`.
    """
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = _enviar(client, ctx, nome="../../../../etc/passwd.mp4")
    assert r.status_code == 201

    with app.app_context():
        post = db.session.get(Post, uuid.UUID(r.get_json()["data"]["post_id"]))
        nome_gravado = post.video_url.rsplit("/", 1)[-1]
        assert ".." not in nome_gravado
        assert "passwd" not in nome_gravado
        # UUID em hex + extensão: nada do que o cliente mandou sobrevive.
        assert len(nome_gravado) == 32 + len(".mp4")


def test_arquivo_que_nao_e_video_e_recusado(client, ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = _enviar(client, ctx, conteudo=b"<html>nao sou video</html>",
                nome="pagina.html", mime="text/html")
    assert r.status_code == 422
    assert r.get_json()["error"]["code"] == "validation_error"


def test_arquivo_vazio_e_recusado(client, ctx, monkeypatch):  # noqa: F811
    """Zero byte passaria pela checagem de tipo e quebraria no modelo."""
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    assert _enviar(client, ctx, conteudo=b"").status_code == 422


def test_sem_arquivo_e_recusado(client, ctx):  # noqa: F811
    r = client.post(
        f"/api/v1/influencers/{ctx.inf_id}/video-analysis",
        headers=ctx.h_admin, data={"caption": "sem arquivo"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422


def test_criador_de_outra_agencia_404(client, ctx, monkeypatch):  # noqa: F811
    """O escopo de agência vale aqui como em qualquer outro recurso."""
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = client.post(
        f"/api/v1/influencers/{ctx.inf_other_id}/video-analysis",
        headers=ctx.h_admin,
        data={"video": (io.BytesIO(b"\x00fake"), "c.mp4", "video/mp4")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 404


def test_viewer_nao_pode_enviar(client, ctx):  # noqa: F811
    r = client.post(
        f"/api/v1/influencers/{ctx.inf_id}/video-analysis",
        headers=ctx.h_viewer,
        data={"video": (io.BytesIO(b"\x00fake"), "c.mp4", "video/mp4")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 403


def test_falha_na_analise_nao_deixa_post_nem_arquivo(client, ctx, app, monkeypatch):  # noqa: F811
    """Análise que estoura não pode deixar rastro.

    Um post sobrevivente apareceria no histórico como publicação que o criador
    nunca fez, e o arquivo ficaria no disco sem nada apontando para ele.
    """
    def explodir(post, **kwargs):
        raise SocialApiError("o modelo recusou")

    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", explodir)

    with app.app_context():
        antes = set(p.name for p in video_upload_service.storage_dir().iterdir())
        posts_antes = len(db.session.scalars(select(Post)).all())

    r = _enviar(client, ctx)
    assert r.status_code >= 400

    with app.app_context():
        depois = set(p.name for p in video_upload_service.storage_dir().iterdir())
        posts_depois = len(db.session.scalars(select(Post)).all())
        assert depois == antes, "arquivo órfão ficou no disco"
        assert posts_depois == posts_antes, "post fantasma sobreviveu"


def test_teto_desta_rota_nao_vaza_para_as_outras(client, ctx, app):  # noqa: F811
    """O limite de 1 MB continua protegendo o resto da API.

    A rota de vídeo eleva `request.max_content_length` na própria requisição.
    Se alguém trocasse isso por elevar `MAX_CONTENT_LENGTH` na configuração, os
    outros endpoints passariam a aceitar corpos enormes sem ninguém notar.
    """
    with app.app_context():
        assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024

    grande = "x" * (2 * 1024 * 1024)
    r = client.patch(
        f"/api/v1/influencers/{ctx.inf_id}",
        headers=ctx.h_admin, json={"bio": grande},
    )
    assert r.status_code == 413


def test_video_em_campanha_cai_dentro_do_periodo(client, ctx, app, monkeypatch):  # noqa: F811
    """O post precisa entrar na janela que o relatório promete na capa."""
    from datetime import date, timedelta

    from src.models import Agency, Campaign

    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    with app.app_context():
        agency = db.session.scalar(select(Agency))
        # Campanha que já terminou: é o caso em que gravar "hoje" deixaria o
        # vídeo fora do próprio relatório para o qual foi enviado.
        camp = Campaign(
            agency_id=agency.id, title="Campanha passada", brand_name="Marca",
            period_start=date.today() - timedelta(days=60),
            period_end=date.today() - timedelta(days=30),
        )
        db.session.add(camp)
        db.session.commit()
        camp_id, inicio, fim = str(camp.id), camp.period_start, camp.period_end

    r = _enviar(client, ctx, extra={"campaign_id": camp_id})
    assert r.status_code == 201

    with app.app_context():
        post = db.session.get(Post, uuid.UUID(r.get_json()["data"]["post_id"]))
        assert inicio <= post.posted_at.date() <= fim


def test_campanha_de_outra_agencia_e_recusada(client, ctx, app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = _enviar(client, ctx, extra={"campaign_id": str(uuid.uuid4())})
    assert r.status_code == 422


def test_campaign_id_malformado_e_recusado(client, ctx):  # noqa: F811
    assert _enviar(client, ctx, extra={"campaign_id": "nao-e-uuid"}).status_code == 422


@pytest.mark.parametrize("mime,extensao", [
    ("video/mp4", ".mp4"),
    ("video/quicktime", ".mov"),
    ("video/webm", ".webm"),
    # Navegador e CDN mandam octet-stream para vídeo legítimo com frequência:
    # recusar por isso rejeitaria envio válido.
    ("application/octet-stream", ".mp4"),
])
def test_extensao_vem_do_tipo_declarado(client, ctx, app, monkeypatch, mime, extensao):  # noqa: F811
    monkeypatch.setattr(video_upload_service, "analyze_post_multimodal", _AnaliseFalsa())

    r = _enviar(client, ctx, nome="qualquer.xyz", mime=mime)
    assert r.status_code == 201

    with app.app_context():
        post = db.session.get(Post, uuid.UUID(r.get_json()["data"]["post_id"]))
        assert post.video_url.endswith(extensao)
