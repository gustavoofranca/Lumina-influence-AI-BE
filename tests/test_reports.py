"""Testes da B10 — geração, listagem e download de relatórios PDF."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import (
    Agency,
    Campaign,
    CampaignInfluencer,
    CampaignStatus,
    Comment,
    Influencer,
    OAuthProvider,
    Platform,
    Post,
    PostType,
    Report,
    SocialAccount,
    User,
    UserRole,
)
from src.services import report_service
from src.utils.jwt_utils import issue_token_pair


class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for m in (Report, Comment, Post, CampaignInfluencer, Campaign, SocialAccount,
                  Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()

        agency = Agency(name="Ag")
        other = Agency(name="Other")
        db.session.add_all([agency, other])
        db.session.flush()
        admin = User(email="a@a.com", name="Admin A", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        viewer = User(email="v@a.com", name="V", oauth_provider=OAuthProvider.GOOGLE,
                      oauth_id="ov", role=UserRole.VIEWER, agency=agency)
        db.session.add_all([admin, viewer])

        inf = Influencer(agency=agency, display_name="Nina Tech", niche="tech")
        db.session.add(inf)
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="nina", follower_count=100000)
        db.session.add(sa)
        db.session.flush()

        camp = Campaign(agency=agency, brand_name="NovaTech", title="Verão Tech",
                        period_start=date(2026, 1, 1), period_end=date(2026, 3, 1),
                        budget_brl_cents=5000000, status=CampaignStatus.ACTIVE)
        camp_other = Campaign(agency=other, brand_name="X", period_start=date(2026, 1, 1),
                              period_end=date(2026, 2, 1), status=CampaignStatus.ACTIVE)
        db.session.add_all([camp, camp_other])
        db.session.flush()
        db.session.add(CampaignInfluencer(campaign=camp, influencer=inf, fee_brl_cents=100000))

        # alguns posts da campanha (pra ter dados no relatório)
        for i in range(3):
            db.session.add(Post(
                social_account=sa, campaign=camp, platform_post_id=f"p{i}",
                post_type=PostType.REEL, posted_at=datetime.now(timezone.utc),
                reach_total=10000, reach_organic=7000, reach_paid=3000, impressions=15000,
                likes=800, comments_count=40, shares=20, saves=30,
            ))
        db.session.commit()

        c = Ctx()
        c.agency_id = agency.id
        c.camp_id = str(camp.id)
        c.camp_other_id = str(camp_other.id)
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.h_viewer = {"Authorization": f"Bearer {issue_token_pair(viewer)['access_token']}"}
        yield c

        # limpa PDFs gerados
        with app.app_context():
            for r in db.session.scalars(select(Report)).all():
                p = report_service.report_pdf_path(r)
                if p.exists():
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            for m in (Report, Comment, Post, CampaignInfluencer, Campaign, SocialAccount,
                      Influencer, User, Agency):
                db.session.query(m).delete()
            db.session.commit()


def _create_payload(camp_id, sections=None):
    return {
        "campaign_id": camp_id,
        "title": "Relatório Verão Tech",
        "period_start": "2026-01-01",
        "period_end": "2026-03-01",
        "sections": sections if sections is not None else ["kpis", "benchmark", "recommendations"],
    }


# ==========================================================================
# POST /reports — gera PDF real
# ==========================================================================
def test_create_report_generates_pdf(client, ctx, app):
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=_create_payload(ctx.camp_id))
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert data["title"] == "Relatório Verão Tech"
    assert data["pdf_url"].endswith("/download")
    assert data["format"] == "pdf"

    with app.app_context():
        report = db.session.get(Report, uuid.UUID(data["id"]))
        path = report_service.report_pdf_path(report)
        assert path.exists()
        assert path.read_bytes()[:5] == b"%PDF-"


def test_create_report_invalid_section_422(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_admin,
                    json=_create_payload(ctx.camp_id, sections=["kpis", "inexistente"]))
    assert r.status_code == 422


def test_create_report_other_agency_campaign_404(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_admin,
                    json=_create_payload(ctx.camp_other_id))
    assert r.status_code == 404


def test_create_report_viewer_forbidden(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_viewer, json=_create_payload(ctx.camp_id))
    assert r.status_code == 403


def test_create_report_invalid_period_422(client, ctx):
    payload = _create_payload(ctx.camp_id)
    payload["period_start"], payload["period_end"] = "2026-03-01", "2026-01-01"
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=payload)
    assert r.status_code == 422


# ==========================================================================
# GET /reports — listagem escopada
# ==========================================================================
def test_list_reports_scoped(client, ctx):
    client.post("/api/v1/reports", headers=ctx.h_admin, json=_create_payload(ctx.camp_id))
    r = client.get("/api/v1/reports", headers=ctx.h_admin)
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) == 1
    assert "pagination" in body["meta"]


# ==========================================================================
# GET /reports/:id/download — baixa o PDF
# ==========================================================================
def test_download_report_returns_pdf(client, ctx):
    created = client.post("/api/v1/reports", headers=ctx.h_admin,
                          json=_create_payload(ctx.camp_id)).get_json()["data"]
    r = client.get(f"/api/v1/reports/{created['id']}/download", headers=ctx.h_admin)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"


def test_download_other_agency_404(client, ctx):
    r = client.get(f"/api/v1/reports/{uuid.uuid4()}/download", headers=ctx.h_admin)
    assert r.status_code == 404


def test_full_sections_report(client, ctx, app):
    """Relatório com todas as seções gera PDF maior sem erro."""
    payload = _create_payload(ctx.camp_id,
                              sections=["kpis", "growth", "benchmark", "diagnostic", "recommendations"])
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=payload)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["sections"]["included"] == ["kpis", "growth", "benchmark", "diagnostic", "recommendations"]
    with app.app_context():
        report = db.session.get(Report, uuid.UUID(data["id"]))
        assert report_service.report_pdf_path(report).read_bytes()[:5] == b"%PDF-"


# ==========================================================================
# POST /reports/preview — mesmo conteúdo do PDF, sem gravar
# ==========================================================================
def test_preview_devolve_o_conteudo_do_relatorio(client, ctx):
    r = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=_create_payload(ctx.camp_id)
    )
    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]

    assert {
        "report_title", "campaign", "period_start", "period_end", "budget_brl",
        "generated_by", "summary", "sections", "kpis", "growth", "benchmark",
        "diagnostic", "recommendations",
    } <= set(data)
    assert data["kpis"], "KPIs sempre existem, mesmo sem post"
    for bucket in data["growth"]:
        # O gráfico da tela precisa do número; o PDF, do texto formatado.
        assert isinstance(bucket["organic"], (int, float))
        assert isinstance(bucket["organic_fmt"], str)


def test_preview_nao_grava_relatorio(client, ctx):
    antes = len(client.get("/api/v1/reports", headers=ctx.h_admin).get_json()["data"])
    client.post("/api/v1/reports/preview", headers=ctx.h_admin, json=_create_payload(ctx.camp_id))
    depois = len(client.get("/api/v1/reports", headers=ctx.h_admin).get_json()["data"])
    assert depois == antes


def test_preview_bate_com_as_secoes_pedidas(client, ctx):
    r = client.post(
        "/api/v1/reports/preview",
        headers=ctx.h_admin,
        json=_create_payload(ctx.camp_id, sections=["kpis", "benchmark"]),
    )
    assert r.get_json()["data"]["sections"] == ["kpis", "benchmark"]


def test_preview_de_campanha_de_outra_agencia_404(client, ctx):
    r = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=_create_payload(ctx.camp_other_id)
    )
    assert r.status_code == 404


def test_preview_secao_invalida_422(client, ctx):
    r = client.post(
        "/api/v1/reports/preview",
        headers=ctx.h_admin,
        json=_create_payload(ctx.camp_id, sections=["kpis", "inexistente"]),
    )
    assert r.status_code == 422


def test_preview_conta_so_os_posts_do_periodo_pedido(client, ctx):
    """A capa declara um intervalo — o corpo precisa ser daquele intervalo.

    Antes, posts e benchmark vinham da campanha inteira: o relatório dizia
    cobrir jan-mar e trazia número de agosto.
    """
    hoje = date.today()
    dentro = _create_payload(ctx.camp_id, sections=["kpis", "growth", "benchmark"])
    dentro["period_start"] = (hoje - timedelta(days=7)).isoformat()
    dentro["period_end"] = (hoje + timedelta(days=1)).isoformat()

    fora = dict(dentro)
    fora["period_start"] = "2020-01-01"
    fora["period_end"] = "2020-12-31"

    d_dentro = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=dentro
    ).get_json()["data"]
    d_fora = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=fora
    ).get_json()["data"]

    # A fixture cria 3 posts com posted_at = agora.
    assert d_dentro["summary"]["posts_count"] == 3
    assert d_dentro["growth"], "há posts na janela, então há trajetória"
    assert d_dentro["benchmark"][0]["total_reach_fmt"] != "0"

    assert d_fora["summary"]["posts_count"] == 0
    assert d_fora["growth"] == []
    assert d_fora["benchmark"][0]["total_reach_fmt"] == "0"


def test_benchmarking_da_campanha_ignora_periodo_por_padrao(client, ctx):
    """A tela de detalhe não escolhe período: continua vendo a campanha toda."""
    rows = client.get(
        f"/api/v1/campaigns/{ctx.camp_id}/benchmarking", headers=ctx.h_admin
    ).get_json()["data"]["influencers"]
    assert rows[0]["posts_count"] == 3


def test_previa_e_pdf_saem_do_mesmo_conteudo(client, ctx, app):
    """O que a tela mostra precisa ser o que o arquivo contém.

    Renderiza o template do PDF com o payload da prévia: se o template passar a
    exigir um campo que o contexto não fornece mais, os números somem do HTML e
    o teste quebra antes de alguém baixar um relatório vazio.
    """
    payload = _create_payload(ctx.camp_id, sections=list(report_service.SECTION_KEYS))
    hoje = date.today()
    payload["period_start"] = (hoje - timedelta(days=7)).isoformat()
    payload["period_end"] = (hoje + timedelta(days=1)).isoformat()

    previa = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=payload
    ).get_json()["data"]

    with app.app_context():
        html = report_service._template.render(**previa)

    resumo = previa["summary"]
    assert f"{resumo['avg_organic_pct']}%" in html
    assert f"{resumo['avg_sentiment_pct']}%" in html
    assert resumo["total_reach_fmt"] in html
    assert str(resumo["posts_count"]) in html
    assert previa["period_start"] in html and previa["period_end"] in html

    for linha in previa["benchmark"]:
        assert linha["display_name"] in html
        assert linha["total_reach_fmt"] in html
    for kpi in previa["kpis"]:
        assert kpi["label"] in html
    for bucket in previa["growth"]:
        assert bucket["organic_fmt"] in html


# ==========================================================================
# Período sem posts — ausência de dado não pode virar desempenho zero
# ==========================================================================
def _previa_sem_posts(client, ctx):
    payload = _create_payload(ctx.camp_id, sections=list(report_service.SECTION_KEYS))
    payload["period_start"] = "2020-01-01"
    payload["period_end"] = "2020-12-31"
    return client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=payload
    ).get_json()["data"]


def test_contexto_marca_quando_o_periodo_nao_tem_post(client, ctx):
    """Sem essa marca, quem renderiza não distingue zero medido de nada medido."""
    assert _previa_sem_posts(client, ctx)["summary"]["has_data"] is False


def test_contexto_marca_periodo_com_post(client, ctx):
    payload = _create_payload(ctx.camp_id, sections=list(report_service.SECTION_KEYS))
    hoje = date.today()
    payload["period_start"] = (hoje - timedelta(days=7)).isoformat()
    payload["period_end"] = (hoje + timedelta(days=1)).isoformat()
    previa = client.post(
        "/api/v1/reports/preview", headers=ctx.h_admin, json=payload
    ).get_json()["data"]
    assert previa["summary"]["has_data"] is True


def test_sumario_sem_posts_nao_afirma_percentual(client, ctx, app):
    """`0.0% do alcance foi orgânico` afirma uma medição que não aconteceu."""
    previa = _previa_sem_posts(client, ctx)
    with app.app_context():
        html = report_service._template.render(**previa)
    assert "do alcance foi orgânico" not in html
    assert "não há dados de performance para auditar" in html


def test_kpis_sem_posts_saem_sem_valor(client, ctx, app):
    """Só os KPIs que dependem de post: a contagem de criadores continua sendo fato."""
    previa = _previa_sem_posts(client, ctx)
    with app.app_context():
        html = report_service._template.render(**previa)

    dependentes = [k for k in previa["kpis"] if k["depends_on_posts"]]
    assert len(dependentes) == 3
    assert all(k["label"] != "Criadores" for k in dependentes)
    assert html.count(">—<") == len(dependentes)


def test_tabelas_sem_posts_trazem_estado_vazio(client, ctx, app):
    """Linha de zeros por criador lê como desempenho nulo; cabeçalho solto lê como bug."""
    previa = _previa_sem_posts(client, ctx)
    with app.app_context():
        html = report_service._template.render(**previa)
    assert "não há dados para comparar" in html
    assert "Nenhum post publicado no período" in html


def test_emoji_sai_do_pdf_e_vai_para_o_log(caplog):
    """Emoji não tem glifo na fonte embarcada e viraria um quadrado preto.

    Remover resolve o visual, mas remover calado esconde o problema de quem
    gerou o documento — daí o aviso em log com o nome do caractere.
    """
    import logging

    from src.utils.pdf_generator import strip_unsupported_glyphs

    with caplog.at_level(logging.WARNING):
        saida = strip_unsupported_glyphs("<h1>Campanha de verão 🚀 e resultados 📈</h1>")

    assert "🚀" not in saida and "📈" not in saida
    assert "Campanha de verão" in saida
    assert "ROCKET" in caplog.text


def test_texto_sem_emoji_passa_intacto_e_sem_aviso(caplog):
    """Acentuação e símbolos tipográficos têm glifo — não podem ser tocados."""
    import logging

    from src.utils.pdf_generator import strip_unsupported_glyphs

    original = "<h1>Análise de Coerência — Ação &amp; Reputação: “aspas”, ç, ã, ñ</h1>"
    with caplog.at_level(logging.WARNING):
        assert strip_unsupported_glyphs(original) == original
    assert caplog.text == ""
