"""Testes da B8 — crypto Fernet, OAuth social (mockado) e sync."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

import src.services.integration_service as isvc
from src.extensions import db
from src.integrations.base import (
    NormalizedComment,
    NormalizedPost,
    OAuthTokenBundle,
    ProfileMetrics,
    TokenRevokedError,
)
from src.models import (
    Agency,
    Comment,
    Influencer,
    OAuthProvider,
    Platform,
    Post,
    PostType,
    SocialAccount,
    User,
    UserRole,
)
from src.utils.crypto import decrypt_token, encrypt_token
from src.utils.jwt_utils import issue_token_pair


# ==========================================================================
# Crypto
# ==========================================================================
def test_crypto_roundtrip(app):
    with app.app_context():
        cipher = encrypt_token("super-secret-token")
        assert cipher != "super-secret-token"
        assert decrypt_token(cipher) == "super-secret-token"


def test_crypto_none_passthrough(app):
    with app.app_context():
        assert encrypt_token(None) is None
        assert decrypt_token(None) is None


def test_crypto_tamper_detection(app):
    from src.utils.crypto import TokenDecryptError

    with app.app_context():
        cipher = encrypt_token("x")
        with pytest.raises(TokenDecryptError):
            decrypt_token(cipher[:-4] + "AAAA")


# ==========================================================================
# Fake adapter
# ==========================================================================
class FakeAdapter:
    platform = "youtube"

    def __init__(self, *, posts=None, revoked=False):
        self._posts = posts or []
        self._revoked = revoked

    def build_auth_url(self, *, state, redirect_uri):
        return f"https://fake.example/auth?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code, redirect_uri):
        return OAuthTokenBundle(
            access_token="acc-123", refresh_token="ref-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            platform_user_id="ch-1", handle="canal_teste",
        )

    def refresh(self, refresh_token):
        return OAuthTokenBundle(
            access_token="acc-refreshed", refresh_token="ref-123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def fetch_profile_metrics(self, access_token):
        if self._revoked:
            raise TokenRevokedError("revogado")
        return ProfileMetrics(follower_count=50000, handle="canal_teste", platform_user_id="ch-1")

    def fetch_recent_posts(self, access_token, limit=10):
        if self._revoked:
            raise TokenRevokedError("revogado")
        return self._posts

    def fetch_post_insights(self, access_token, platform_post_id):
        return {}

    def fetch_post_comments(self, access_token, platform_post_id, limit=15):
        return [
            NormalizedComment(
                platform_comment_id=f"{platform_post_id}-c1", content="top!",
                author_handle="viewer", posted_at=datetime.now(timezone.utc), like_count=3,
            )
        ]


def _np(pid):
    return NormalizedPost(
        platform_post_id=pid, post_type=PostType.VIDEO,
        posted_at=datetime.now(timezone.utc), caption="vídeo novo",
        reach_total=1000, reach_organic=800, reach_paid=200, impressions=1500,
        likes=100, comments_count=10, shares=5, saves=8,
    )


# ==========================================================================
# Fixture
# ==========================================================================
class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for m in (Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()

        agency = Agency(name="Ag")
        other = Agency(name="Other")
        db.session.add_all([agency, other])
        db.session.flush()

        admin = User(email="a@a.com", name="A", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        viewer = User(email="v@a.com", name="V", oauth_provider=OAuthProvider.GOOGLE,
                      oauth_id="ov", role=UserRole.VIEWER, agency=agency)
        db.session.add_all([admin, viewer])

        inf = Influencer(agency=agency, display_name="Inf", niche="tech")
        inf_other = Influencer(agency=other, display_name="Other Inf", niche="x")
        db.session.add_all([inf, inf_other])
        db.session.flush()

        # conta seedada SEM token (pra testar sync simulado)
        sa = SocialAccount(influencer=inf, platform=Platform.YOUTUBE, handle="canal",
                           follower_count=1000)
        db.session.add(sa)
        db.session.flush()
        db.session.add(Post(social_account=sa, platform_post_id="old-1", post_type=PostType.VIDEO,
                            posted_at=datetime.now(timezone.utc), reach_total=500, reach_organic=400,
                            reach_paid=100, impressions=800, likes=50, comments_count=5, shares=2, saves=3))
        db.session.commit()

        c = Ctx()
        c.agency_id = agency.id
        c.inf_id = str(inf.id)
        c.inf_other_id = str(inf_other.id)
        c.sa_id = str(sa.id)
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.h_viewer = {"Authorization": f"Bearer {issue_token_pair(viewer)['access_token']}"}
        yield c

        for m in (Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()


# ==========================================================================
# Connect
# ==========================================================================
def test_connect_returns_auth_url_with_state(client, ctx):
    r = client.get(f"/api/v1/integrations/youtube/connect?influencer_id={ctx.inf_id}", headers=ctx.h_admin)
    assert r.status_code == 200
    auth_url = r.get_json()["data"]["auth_url"]
    assert "accounts.google.com" in auth_url
    qs = parse_qs(urlparse(auth_url).query)
    assert "state" in qs


def test_connect_requires_influencer_id(client, ctx):
    r = client.get("/api/v1/integrations/youtube/connect", headers=ctx.h_admin)
    assert r.status_code == 422


def test_connect_other_agency_influencer_404(client, ctx):
    r = client.get(
        f"/api/v1/integrations/youtube/connect?influencer_id={ctx.inf_other_id}", headers=ctx.h_admin
    )
    assert r.status_code == 404


def test_connect_viewer_forbidden(client, ctx):
    r = client.get(f"/api/v1/integrations/youtube/connect?influencer_id={ctx.inf_id}", headers=ctx.h_viewer)
    assert r.status_code == 403


def test_connect_unknown_platform_404(client, ctx):
    r = client.get(f"/api/v1/integrations/myspace/connect?influencer_id={ctx.inf_id}", headers=ctx.h_admin)
    assert r.status_code == 404


# ==========================================================================
# Callback (mock adapter)
# ==========================================================================
def test_callback_creates_account_with_encrypted_tokens(client, ctx, app, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    # gera state válido
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_id), platform=Platform.YOUTUBE, agency_id=ctx.agency_id
        )

    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}", headers=ctx.h_admin)
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert data["handle"] == "canal_teste"
    assert data["follower_count"] == 50000
    # token nunca exposto no Out
    assert "access_token_encrypted" not in data

    with app.app_context():
        acc = db.session.scalar(
            select(SocialAccount).where(SocialAccount.platform_user_id == "ch-1")
        )
        assert acc.access_token_encrypted is not None
        assert acc.access_token_encrypted != "acc-123"  # cifrado
        assert decrypt_token(acc.access_token_encrypted) == "acc-123"


def test_callback_rejects_tampered_state(client, ctx, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    r = client.get("/api/v1/integrations/youtube/callback?code=abc&state=garbage", headers=ctx.h_admin)
    assert r.status_code == 401


def test_callback_state_platform_mismatch(client, ctx, app, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_id), platform=Platform.TIKTOK, agency_id=ctx.agency_id
        )
    # state é de tiktok, callback é youtube → mismatch
    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}", headers=ctx.h_admin)
    assert r.status_code == 401


# ==========================================================================
# Disconnect
# ==========================================================================
def test_disconnect_clears_tokens(client, ctx):
    # Muta na sessão ambiente (a mesma que a request reusa no test client).
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    acc.access_token_encrypted = encrypt_token("tok")
    acc.refresh_token_encrypted = encrypt_token("ref")
    db.session.commit()

    r = client.post(f"/api/v1/integrations/youtube/disconnect/{ctx.sa_id}", headers=ctx.h_admin)
    assert r.status_code == 200

    db.session.expire_all()
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    assert acc.access_token_encrypted is None
    assert acc.refresh_token_encrypted is None


# ==========================================================================
# Sync
# ==========================================================================
def test_sync_simulated_when_no_token(client, ctx, app):
    """Conta seedada sem token → modo simulado, atualiza posts existentes."""
    r = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)
    assert r.status_code == 200
    accounts = r.get_json()["data"]["accounts"]
    assert accounts[0]["mode"] == "simulated"
    assert accounts[0]["posts_updated"] >= 1


def test_sync_real_when_token_present(client, ctx, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter(posts=[_np("yt-new-1")]))
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    acc.access_token_encrypted = encrypt_token("valid-token")
    acc.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.session.commit()

    r = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)
    assert r.status_code == 200
    acc_result = r.get_json()["data"]["accounts"][0]
    assert acc_result["mode"] == "real"
    assert acc_result["posts_created"] == 1

    db.session.expire_all()
    new_post = db.session.scalar(select(Post).where(Post.platform_post_id == "yt-new-1"))
    assert new_post is not None
    assert new_post.needs_analysis is True
    n_comments = db.session.scalar(
        select(func.count(Comment.id)).where(Comment.post_id == new_post.id)
    )
    assert n_comments == 1


def test_sync_refreshes_expired_token(client, ctx, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter(posts=[]))
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    acc.access_token_encrypted = encrypt_token("old-token")
    acc.refresh_token_encrypted = encrypt_token("ref-token")
    acc.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)  # expirado
    db.session.commit()

    r = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)
    assert r.status_code == 200

    db.session.expire_all()
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    # token foi renovado e repersistido cifrado
    assert decrypt_token(acc.access_token_encrypted) == "acc-refreshed"


def test_sync_handles_revoked_token(client, ctx, monkeypatch):
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter(revoked=True))
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    acc.access_token_encrypted = encrypt_token("revoked-token")
    acc.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.session.commit()

    r = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)
    assert r.status_code == 200
    assert r.get_json()["data"]["accounts"][0]["status"] == "token_revoked"

    db.session.expire_all()
    acc = db.session.get(SocialAccount, uuid.UUID(ctx.sa_id))
    assert acc.access_token_encrypted is None  # limpo pra reconexão
