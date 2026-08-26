"""Testes da B12 — rate limit, OpenAPI/Swagger."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from src.config import ProdConfig, StagingConfig
from src.extensions import db
from src.models import (
    Agency,
    Campaign,
    CampaignInfluencer,
    CampaignStatus,
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
from src.utils.rate_limit import RateLimitExceeded, _check, reset_rate_limits


# ==========================================================================
# Unidade do limiter
# ==========================================================================
def test_rate_limit_allows_under_limit():
    reset_rate_limits()
    for _ in range(3):
        _check("k1", limit=3, window=60)  # não levanta


def test_rate_limit_blocks_over_limit():
    reset_rate_limits()
    for _ in range(3):
        _check("k2", limit=3, window=60)
    with pytest.raises(RateLimitExceeded):
        _check("k2", limit=3, window=60)


def test_rate_limit_isolated_per_key():
    reset_rate_limits()
    _check("a", limit=1, window=60)
    _check("b", limit=1, window=60)  # chave diferente, ok
    with pytest.raises(RateLimitExceeded):
        _check("a", limit=1, window=60)


# ==========================================================================
# Rate limit no endpoint /reports
# ==========================================================================
@pytest.fixture()
def report_ctx(app):
    with app.app_context():
        for m in (Report, Post, CampaignInfluencer, Campaign, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()
        agency = Agency(name="RL Ag")
        db.session.add(agency)
        db.session.flush()
        admin = User(email="rl@a.com", name="RL", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        inf = Influencer(agency=agency, display_name="I", niche="t")
        db.session.add_all([admin, inf])
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="h")
        db.session.add(sa)
        db.session.flush()
        camp = Campaign(agency=agency, brand_name="B", period_start=date(2026, 1, 1),
                        period_end=date(2026, 2, 1), status=CampaignStatus.ACTIVE)
        db.session.add(camp)
        db.session.flush()
        db.session.add(CampaignInfluencer(campaign=camp, influencer=inf, fee_brl_cents=1))
        db.session.add(Post(social_account=sa, campaign=camp, platform_post_id="p1",
                            post_type=PostType.REEL, posted_at=datetime.now(timezone.utc),
                            reach_total=100, reach_organic=70, reach_paid=30, impressions=150,
                            likes=10, comments_count=2, shares=1, saves=1))
        db.session.commit()
        c = type("C", (), {})()
        c.camp_id = str(camp.id)
        c.h = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        yield c
        for r in db.session.scalars(select(Report)).all():
            p = report_service.report_pdf_path(r)
            if p.exists():
                import os
                os.remove(p)
        for m in (Report, Post, CampaignInfluencer, Campaign, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()


def test_reports_rate_limited(client, report_ctx, app, monkeypatch):
    reset_rate_limits()
    # Limite baixo só pra este teste.
    monkeypatch.setitem(app.config, "RATE_LIMIT_REPORTS", {"limit": 2, "window": 60})

    payload = {
        "campaign_id": report_ctx.camp_id, "title": "R",
        "period_start": "2026-01-01", "period_end": "2026-02-01", "sections": ["kpis"],
    }
    assert client.post("/api/v1/reports", headers=report_ctx.h, json=payload).status_code == 201
    assert client.post("/api/v1/reports", headers=report_ctx.h, json=payload).status_code == 201
    r3 = client.post("/api/v1/reports", headers=report_ctx.h, json=payload)
    assert r3.status_code == 429
    assert r3.get_json()["error"]["code"] == "rate_limit_exceeded"


# ==========================================================================
# OpenAPI / Swagger
# ==========================================================================
def test_openapi_spec(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    spec = r.get_json()
    assert spec["openapi"].startswith("3.")
    assert "/api/v1/influencers" in spec["paths"]
    assert "InfluencerOut" in spec["components"]["schemas"]
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"


def test_swagger_ui_served(client):
    r = client.get("/api/v1/docs")
    assert r.status_code == 200
    assert b"swagger-ui" in r.data


# ==========================================================================
# Cabeçalhos de segurança
# ==========================================================================
def test_resposta_traz_cabecalhos_de_seguranca(client):
    r = client.get("/api/v1/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_cabecalhos_tambem_valem_para_respostas_de_erro(client):
    """O handler global de erro não pode escapar dos cabeçalhos."""
    r = client.get("/api/v1/rota-que-nao-existe")
    assert r.status_code == 404
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_hsts_ausente_em_conexao_nao_segura(client):
    """Anunciar HSTS em http local fixaria o navegador num host sem TLS."""
    r = client.get("/api/v1/health")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_presente_em_conexao_segura(client):
    r = client.get("/api/v1/health", base_url="https://lumina.local")
    assert "max-age=" in r.headers["Strict-Transport-Security"]


@pytest.mark.parametrize("config_cls", [StagingConfig, ProdConfig])
def test_dev_login_desligado_fora_de_desenvolvimento(config_cls, monkeypatch):
    """O atalho emite JWT de admin sem OAuth — variável de ambiente não pode religá-lo."""
    monkeypatch.setenv("DEV_LOGIN_ENABLED", "true")
    assert config_cls.DEV_LOGIN_ENABLED is False


# Rotas que ficam fora da spec de propósito. `/docs` e `/openapi.json` são a
# própria infraestrutura da documentação; `dev-login` é atalho de ambiente de
# desenvolvimento e não faz parte do contrato público da API.
ROTAS_FORA_DA_SPEC = {
    ("get", "/api/v1/docs"),
    ("get", "/api/v1/openapi.json"),
    ("post", "/api/v1/auth/dev-login"),
}


def _rotas_reais(app) -> set[tuple[str, str]]:
    """(método, path) de cada rota real, com o parâmetro normalizado para {id}."""
    rotas = set()
    for regra in app.url_map.iter_rules():
        if regra.endpoint.startswith("static"):
            continue
        path = re.sub(r"<[^:>]*:?([^>]*)>", "{id}", str(regra))
        for metodo in regra.methods:
            if metodo in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                rotas.add((metodo.lower(), path))
    return rotas


def test_toda_rota_esta_na_spec_openapi(client, app):
    """Rota fora do Swagger é rota que o front descobre lendo o código.

    Este teste falha quando alguém adiciona um endpoint e esquece a spec — que
    foi exatamente como 14 rotas ficaram de fora sem ninguém perceber.
    """
    spec = client.get("/api/v1/openapi.json").get_json()
    documentadas = {
        (metodo, re.sub(r"\{[^}]*\}", "{id}", path))
        for path, ops in spec["paths"].items()
        for metodo in ops
        if metodo in {"get", "post", "patch", "put", "delete"}
    }
    faltando = _rotas_reais(app) - documentadas - ROTAS_FORA_DA_SPEC
    assert not faltando, f"rotas sem documentação na spec: {sorted(faltando)}"


def test_spec_nao_documenta_rota_inexistente(client, app):
    """O caminho inverso: spec que promete endpoint que não existe engana quem integra."""
    spec = client.get("/api/v1/openapi.json").get_json()
    documentadas = {
        (metodo, re.sub(r"\{[^}]*\}", "{id}", path))
        for path, ops in spec["paths"].items()
        for metodo in ops
        if metodo in {"get", "post", "patch", "put", "delete"}
    }
    assert not documentadas - _rotas_reais(app)
