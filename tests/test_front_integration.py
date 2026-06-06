"""Testes das mudanças de back-end para a integração com o front (B11)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import Agency, Influencer, OAuthProvider, Plan, Post, PostType, SocialAccount, Platform, User, UserRole
from datetime import datetime, timezone


@pytest.fixture()
def seeded_user(app):
    with app.app_context():
        for m in (User, Agency):
            db.session.query(m).delete()
        db.session.commit()
        agency = Agency(name="Ag")
        db.session.add(agency)
        db.session.flush()
        admin = User(email="admin@lumina-agency.com.br", name="Admin", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        db.session.add(admin)
        db.session.commit()
        yield
        for m in (User, Agency):
            db.session.query(m).delete()
        db.session.commit()


# ==========================================================================
# dev-login
# ==========================================================================
def test_dev_login_default_admin(client, seeded_user):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert data["user"]["email"] == "admin@lumina-agency.com.br"
    assert "access_token" in data["tokens"]


def test_dev_login_by_email(client, seeded_user):
    r = client.post("/api/v1/auth/dev-login", json={"email": "admin@lumina-agency.com.br"})
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["role"] == "admin"


def test_dev_login_unknown_email_401(client, seeded_user):
    r = client.post("/api/v1/auth/dev-login", json={"email": "naoexiste@x.com"})
    assert r.status_code == 401


def test_dev_login_disabled(client, seeded_user, app, monkeypatch):
    monkeypatch.setitem(app.config, "DEV_LOGIN_ENABLED", False)
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "dev_login_disabled"


# ==========================================================================
# callback redirect pro front
# ==========================================================================
def test_callback_redirects_to_front_when_configured(client, seeded_user, app, monkeypatch):
    import src.api.auth as auth_api
    from src.integrations.base_oauth import OAuthUserInfo
    from src.integrations.google_oauth import GoogleOAuthClient

    monkeypatch.setitem(app.config, "AUTH_SUCCESS_REDIRECT", "http://localhost:5173/auth/callback")
    monkeypatch.setattr(GoogleOAuthClient, "exchange_code", lambda self, **k: {"access_token": "x"})
    monkeypatch.setattr(GoogleOAuthClient, "fetch_user_info",
                        lambda self, tok: OAuthUserInfo(provider="google", oauth_id="g1",
                                                        email="novo@ext.com", name="Novo"))
    # state válido
    r0 = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r0.headers["Location"]).query)["state"][0]

    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={state}")
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert loc.startswith("http://localhost:5173/auth/callback#")
    frag = parse_qs(urlparse(loc).fragment)
    assert "access_token" in frag and "refresh_token" in frag


# ==========================================================================
# /influencers?enriched=true
# ==========================================================================
def test_influencers_enriched_includes_metrics(client, app):
    from src.utils.jwt_utils import issue_token_pair

    with app.app_context():
        for m in (Post, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()
        agency = Agency(name="Ag")
        db.session.add(agency)
        db.session.flush()
        admin = User(email="a@a.com", name="A", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        inf = Influencer(agency=agency, display_name="Nina", niche="tech")
        db.session.add_all([admin, inf])
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="nina", follower_count=1000)
        db.session.add(sa)
        db.session.flush()
        db.session.add(Post(social_account=sa, platform_post_id="p1", post_type=PostType.REEL,
                            posted_at=datetime.now(timezone.utc), reach_total=1000, reach_organic=700,
                            reach_paid=300, impressions=1500, likes=100, comments_count=10, shares=5, saves=8))
        db.session.commit()
        h = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}

    r = client.get("/api/v1/influencers?enriched=true", headers=h)
    assert r.status_code == 200
    item = r.get_json()["data"][0]
    assert "metrics" in item
    assert "resonance_score" in item["metrics"]
    assert "engagement_rate" in item["metrics"]

    # sem enriched, não vem metrics
    r2 = client.get("/api/v1/influencers", headers=h)
    assert "metrics" not in r2.get_json()["data"][0]
