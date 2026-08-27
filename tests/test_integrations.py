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
    PlatformNotConfiguredError,
    ProfileMetrics,
    TokenRevokedError,
    raise_for_social_status,
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

    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")
    # O callback é navegação de browser: termina em redirect, não em JSON.
    assert r.status_code == 302, r.data

    with app.app_context():
        acc = db.session.scalar(
            select(SocialAccount).where(SocialAccount.platform_user_id == "ch-1")
        )
        assert acc.handle == "canal_teste"
        assert acc.follower_count == 50000
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


# ==========================================================================
# Callback sem sessão — é o browser que chega, não o front
# ==========================================================================
def test_callback_conclui_sem_bearer(client, ctx, app, monkeypatch):
    """O provedor redireciona o browser, e navegação não carrega Authorization.

    Com @require_auth no callback o fluxo devolvia 401 antes de fazer qualquer
    coisa — verde nos testes, que mandavam o header na mão, e impossível na
    vida real. A identidade vem do state assinado.
    """
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_id), platform=Platform.YOUTUBE,
            agency_id=ctx.agency_id,
        )

    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")

    assert r.status_code == 302, r.data
    assert ctx.inf_id in r.headers["Location"]


def test_callback_recusa_state_reapresentado(client, ctx, app, monkeypatch):
    """Sem sessão, o uso único do state é o que impede reapresentação."""
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_id), platform=Platform.YOUTUBE,
            agency_id=ctx.agency_id,
        )

    primeira = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")
    assert primeira.status_code == 302

    segunda = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")
    assert segunda.status_code == 401
    assert segunda.get_json()["error"]["code"] == "oauth_state_replayed"


def test_callback_recusa_influencer_de_outra_agencia(client, ctx, app, monkeypatch):
    """O state diz a agência; o influencer precisa pertencer a ela agora."""
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_other_id), platform=Platform.YOUTUBE,
            agency_id=ctx.agency_id,
        )

    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")
    assert r.status_code == 404


def test_callback_redireciona_para_a_tela_do_criador(client, ctx, app, monkeypatch):
    """O destino é a origem do front, não a página de callback do login.

    AUTH_SUCCESS_REDIRECT aponta para /auth/callback: usá-la como base produziria
    /auth/callback/app/influenciadores/... — uma rota que não existe.
    """
    monkeypatch.setattr(isvc, "get_adapter", lambda platform: FakeAdapter())
    with app.app_context():
        state = isvc.mint_state(
            influencer_id=uuid.UUID(ctx.inf_id), platform=Platform.YOUTUBE,
            agency_id=ctx.agency_id,
        )
    r = client.get(f"/api/v1/integrations/youtube/callback?code=abc&state={state}")

    assert r.status_code == 302
    assert r.headers["Location"].startswith(
        f"http://localhost:5173/app/influenciadores/{ctx.inf_id}"
    )
    assert "conectado=youtube" in r.headers["Location"]


# ==========================================================================
# Credencial do app errada não é token do usuário revogado
# ==========================================================================
class _Resp:
    """Resposta mínima no formato que `raise_for_social_status` consome."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def test_invalid_client_vira_erro_de_configuracao_nao_token_revogado():
    """`invalid_client` é secret do app errado, não token do usuário.

    A distinção não é cosmética: `sync_influencer` apaga os tokens da conta ao
    ver TokenRevokedError. Classificar erro de configuração como revogação
    destruiria a conexão válida do criador por causa de um `.env` errado.
    """
    body = '{"error": "invalid_client", "error_description": "The provided client secret is invalid."}'

    with pytest.raises(PlatformNotConfiguredError) as exc:
        raise_for_social_status(_Resp(401, body), platform="youtube")

    assert exc.value.code == "platform_not_configured"
    assert exc.value.status_code == 503


def test_invalid_grant_continua_sendo_token_revogado():
    """`invalid_grant` é o refresh revogado pelo usuário — reconexão é o caminho."""
    body = '{"error": "invalid_grant", "error_description": "Token has been expired or revoked."}'

    with pytest.raises(TokenRevokedError):
        raise_for_social_status(_Resp(400, body), platform="youtube")


def test_401_sem_marcador_de_credencial_continua_token_revogado():
    """O caso comum de 401 (token do usuário inválido) não pode mudar de classe."""
    with pytest.raises(TokenRevokedError):
        raise_for_social_status(_Resp(401, '{"error": {"message": "Invalid Credentials"}}'),
                                platform="youtube")


def test_sync_com_credencial_errada_preserva_o_token_do_criador(app, ctx, monkeypatch):
    """Erro de configuração não pode zerar o token guardado da conta."""
    class CredencialErrada(FakeAdapter):
        def refresh(self, refresh_token):
            raise PlatformNotConfiguredError("youtube: credencial do app inválida")

        def fetch_recent_posts(self, access_token, limit=10):
            raise PlatformNotConfiguredError("youtube: credencial do app inválida")

    with app.app_context():
        account = db.session.scalar(
            select(SocialAccount).where(SocialAccount.influencer_id == uuid.UUID(ctx.inf_id))
        )
        account.access_token_encrypted = encrypt_token("acc-valido")
        account.refresh_token_encrypted = encrypt_token("ref-valido")
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.session.commit()
        influencer = db.session.get(Influencer, uuid.UUID(ctx.inf_id))

        with pytest.raises(PlatformNotConfiguredError):
            isvc.sync_influencer(influencer, adapter_factory=lambda p: CredencialErrada())

        db.session.rollback()
        account = db.session.scalar(
            select(SocialAccount).where(SocialAccount.influencer_id == uuid.UUID(ctx.inf_id))
        )
        assert account.access_token_encrypted is not None
        assert decrypt_token(account.access_token_encrypted) == "acc-valido"
