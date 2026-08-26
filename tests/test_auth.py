"""Testes do fluxo OAuth + JWT.

Estratégia: mockar GoogleOAuthClient.exchange_code/fetch_user_info via monkeypatch.
Não testamos endpoints reais do Google — isso é validado manualmente.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.extensions import db
from src.integrations.base_oauth import OAuthUserInfo
from src.integrations.google_oauth import GoogleOAuthClient
from src.models import Agency, OAuthState, User, UserRole
from src.models._enums import OAuthProvider
from src.utils.jwt_utils import encode_token, issue_token_pair


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def clean_db(app):
    """Garante banco vazio antes do teste; rollback ao final."""
    with app.app_context():
        for model in (User, Agency, OAuthState):
            db.session.query(model).delete()
        db.session.commit()
        yield
        for model in (User, Agency, OAuthState):
            db.session.query(model).delete()
        db.session.commit()


@pytest.fixture()
def fake_google(monkeypatch):
    """Faz GoogleOAuthClient retornar dados fixos sem bater na rede."""

    def _exchange(self, *, code, redirect_uri):
        return {"access_token": "fake-access", "id_token": "fake-id"}

    monkeypatch.setattr(GoogleOAuthClient, "exchange_code", _exchange)
    return monkeypatch


def _patch_userinfo(monkeypatch, *, sub, email, name, avatar=None):
    def _info(self, access_token):
        return OAuthUserInfo(
            provider="google", oauth_id=sub, email=email, name=name, avatar_url=avatar
        )

    monkeypatch.setattr(GoogleOAuthClient, "fetch_user_info", _info)


# --------------------------------------------------------------------------
# /auth/google/login
# --------------------------------------------------------------------------
def test_google_login_redirects_with_persisted_state(client, clean_db, app):
    r = client.get("/api/v1/auth/google/login")
    assert r.status_code == 302
    loc = r.headers["Location"]
    qs = parse_qs(urlparse(loc).query)
    assert "state" in qs
    state = qs["state"][0]

    with app.app_context():
        record = db.session.scalar(
            select(OAuthState).where(OAuthState.state_token == state)
        )
        assert record is not None
        assert record.provider == OAuthProvider.GOOGLE


# --------------------------------------------------------------------------
# /auth/google/callback
# --------------------------------------------------------------------------
def test_google_callback_creates_user_and_agency_for_new_email(
    client, clean_db, fake_google, monkeypatch, app
):
    # Inicia login pra obter state válido
    r = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]

    _patch_userinfo(
        monkeypatch, sub="g-12345", email="novo@teste.com", name="Novo Usuário"
    )

    r = client.get(f"/api/v1/auth/google/callback?code=fake-code&state={state}")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert data["user"]["email"] == "novo@teste.com"
    assert data["user"]["role"] == "admin"
    assert data["agency"]["name"] == "Minha Agência"
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]


def test_google_callback_relinks_existing_seed_user(
    client, clean_db, fake_google, monkeypatch, app
):
    """Email já existente: atualiza oauth_id real, mantém agência."""
    with app.app_context():
        agency = Agency(name="Lumina Seedada")
        user = User(
            email="marina@lumina-agency.com.br",
            name="Marina (seed)",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="seed-google-usr-001",  # fake do seed
            role=UserRole.ADMIN,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        seed_user_id = user.id

    r = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    _patch_userinfo(
        monkeypatch,
        sub="real-google-sub-9876",
        email="marina@lumina-agency.com.br",
        name="Marina Real",
        avatar="https://lh3.googleusercontent.com/a/123",
    )

    r = client.get(f"/api/v1/auth/google/callback?code=fake-code&state={state}")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["user"]["id"] == str(seed_user_id), "deveria reusar mesmo user"

    with app.app_context():
        refreshed = db.session.get(User, seed_user_id)
        assert refreshed.oauth_id == "real-google-sub-9876"
        assert refreshed.avatar_url == "https://lh3.googleusercontent.com/a/123"


def test_google_callback_rejects_invalid_state(client, clean_db, fake_google):
    r = client.get("/api/v1/auth/google/callback?code=x&state=fake-state-not-in-db")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "oauth_state_invalid"


def test_google_callback_rejects_expired_state(
    client, clean_db, fake_google, monkeypatch, app
):
    r = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]

    # Expira manualmente
    with app.app_context():
        record = db.session.scalar(
            select(OAuthState).where(OAuthState.state_token == state)
        )
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

    r = client.get(f"/api/v1/auth/google/callback?code=x&state={state}")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "oauth_state_expired"


def test_google_callback_handles_provider_error(client, clean_db):
    r = client.get(
        "/api/v1/auth/google/callback?error=access_denied&error_description=user_cancelled"
    )
    assert r.status_code == 422
    body = r.get_json()["error"]
    assert "Google retornou erro" in body["message"]


# --------------------------------------------------------------------------
# /auth/me
# --------------------------------------------------------------------------
def test_me_returns_user_with_valid_token(client, clean_db, app):
    with app.app_context():
        agency = Agency(name="Test Agency")
        user = User(
            email="u@t.com",
            name="U",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="x",
            role=UserRole.MEMBER,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        tokens = issue_token_pair(user)

    r = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["email"] == "u@t.com"


def test_me_rejects_missing_token(client, clean_db):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "missing_bearer"


def test_me_rejects_garbage_token(client, clean_db):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "token_invalid"


def test_me_rejects_refresh_token(client, clean_db, app):
    """Refresh token não pode ser usado pra autenticar requests normais."""
    with app.app_context():
        agency = Agency(name="A")
        user = User(
            email="x@y.com",
            name="X",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="z",
            role=UserRole.MEMBER,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        refresh = encode_token(token_type="refresh", user_id=user.id)

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "token_wrong_type"


# --------------------------------------------------------------------------
# /auth/refresh
# --------------------------------------------------------------------------
def test_refresh_issues_new_access_token(client, clean_db, app):
    with app.app_context():
        agency = Agency(name="A")
        user = User(
            email="a@b.com",
            name="A",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="i",
            role=UserRole.MEMBER,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        refresh = encode_token(token_type="refresh", user_id=user.id)

    r = client.post(
        "/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh}"}
    )
    assert r.status_code == 200
    body = r.get_json()["data"]
    assert "access_token" in body
    assert "refresh_token" in body


def test_refresh_rejects_access_token(client, clean_db, app):
    with app.app_context():
        agency = Agency(name="A")
        user = User(
            email="a@b.com",
            name="A",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="i",
            role=UserRole.MEMBER,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        access = encode_token(token_type="access", user_id=user.id)

    r = client.post(
        "/api/v1/auth/refresh", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "token_wrong_type"


# --------------------------------------------------------------------------
# /auth/logout
# --------------------------------------------------------------------------
def test_logout_returns_204(client, clean_db, app):
    with app.app_context():
        agency = Agency(name="A")
        user = User(
            email="logout@t.com",
            name="L",
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_id="i",
            role=UserRole.MEMBER,
            agency=agency,
        )
        db.session.add_all([agency, user])
        db.session.commit()
        access = encode_token(token_type="access", user_id=user.id)

    r = client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 204


def test_google_callback_nao_aceita_o_mesmo_state_duas_vezes(
    client, clean_db, fake_google, monkeypatch, app
):
    """O state precisa ser de uso único.

    Um state que continua valendo depois do primeiro uso permite replay: quem
    interceptar a URL de callback (histórico do navegador, log de proxy, um
    Referer vazado) reencena o login e recebe um par de tokens novo.
    """
    r = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    _patch_userinfo(monkeypatch, sub="g-replay", email="replay@teste.com", name="Replay")

    primeira = client.get(f"/api/v1/auth/google/callback?code=fake-code&state={state}")
    assert primeira.status_code == 200

    segunda = client.get(f"/api/v1/auth/google/callback?code=fake-code&state={state}")
    assert segunda.status_code == 401
    assert segunda.get_json()["error"]["code"] == "oauth_state_invalid"


def test_google_callback_devolve_os_tokens_no_fragmento_da_url(
    client, clean_db, fake_google, monkeypatch, app
):
    """Com AUTH_SUCCESS_REDIRECT configurado, o callback volta para o front.

    Os tokens têm que ir no fragmento (#), nunca na query (?): o fragmento não
    é enviado ao servidor, não entra em log de acesso nem em cabeçalho Referer.
    """
    app.config["AUTH_SUCCESS_REDIRECT"] = "http://localhost:5173/auth/callback"
    try:
        r = client.get("/api/v1/auth/google/login")
        state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
        _patch_userinfo(monkeypatch, sub="g-frag", email="frag@teste.com", name="Frag")

        r = client.get(f"/api/v1/auth/google/callback?code=fake-code&state={state}")
        assert r.status_code == 302

        destino = urlparse(r.headers["Location"])
        assert destino.path == "/auth/callback"
        assert "access_token" not in destino.query
        assert "access_token" in parse_qs(destino.fragment)
        assert "refresh_token" in parse_qs(destino.fragment)
    finally:
        app.config["AUTH_SUCCESS_REDIRECT"] = None
