"""Refresh token em cookie httpOnly (ADR-001, revisão de 25/11/2026)."""
from __future__ import annotations

from src.extensions import db
from src.models import User
from src.utils.jwt_utils import encode_token

COOKIE = "lumina_refresh"
CAMINHO = "/api/v1/auth"
CSRF = {"X-Lumina-Csrf": "1"}


def _entrar(client, email):
    r = client.post("/api/v1/auth/dev-login", json={"email": email})
    assert r.status_code == 200, r.get_json()
    return r


def test_login_grava_cookie_httponly_strict_e_tira_o_refresh_do_corpo(client, conta_com_senha):
    r = _entrar(client, conta_com_senha.email)
    assert "refresh_token" not in r.get_json()["data"]["tokens"]
    cabecalho = r.headers["Set-Cookie"]
    assert cabecalho.startswith(f"{COOKIE}=")
    for atributo in ("HttpOnly", "SameSite=Strict", f"Path={CAMINHO}", "Max-Age=2592000"):
        assert atributo in cabecalho


def test_cookie_e_secure_fora_de_dev(app, client, conta_com_senha, monkeypatch):
    monkeypatch.setitem(app.config, "REFRESH_COOKIE_SECURE", True)
    r = _entrar(client, conta_com_senha.email)
    assert "Secure" in r.headers["Set-Cookie"]


def test_refresh_pelo_cookie_devolve_access_novo(client, conta_com_senha):
    _entrar(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    access = r.get_json()["data"]["tokens"]["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200


def test_refresh_pelo_cookie_sem_cabecalho_anti_csrf_e_recusado(client, conta_com_senha):
    _entrar(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "csrf_header_missing"


def test_refresh_sem_cookie_e_sem_bearer_da_401(client):
    r = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 401


def test_bearer_prevalece_sobre_cookie_antigo(app, client, conta_com_senha):
    """O callback do Google troca o refresh do fragmento pelo Bearer; um cookie
    de quem usou o navegador antes não pode decidir de quem é a sessão."""
    from src.models import Agency, UserRole

    _entrar(client, conta_com_senha.email)
    with app.app_context():
        outra = Agency(name="Outra")
        pessoa = User(email="outra@x.com", name="Outra Pessoa", role=UserRole.MEMBER, agency=outra)
        db.session.add_all([outra, pessoa])
        db.session.commit()
        refresh = encode_token(token_type="refresh", user_id=pessoa.id)
        pessoa_id, agencia_id = pessoa.id, outra.id
    try:
        r = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh}"})
        assert r.status_code == 200
        access = r.get_json()["data"]["tokens"]["access_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.get_json()["data"]["user"]["id"] == str(pessoa_id)
    finally:
        with app.app_context():
            db.session.delete(db.session.get(User, pessoa_id))
            db.session.delete(db.session.get(Agency, agencia_id))
            db.session.commit()


def test_logout_apaga_o_cookie_mesmo_sem_access_token(client, conta_com_senha):
    _entrar(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert client.get_cookie(COOKIE, path=CAMINHO) is None
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_ticket_de_2fa_nao_grava_cookie(client, conta_com_senha):
    """Admin sem 2FA recebe ticket de ativação, que não é sessão."""
    r = client.post(
        "/api/v1/auth/login",
        json={"email": conta_com_senha.email, "password": conta_com_senha.senha},
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["data"].get("mfa")
    assert "Set-Cookie" not in r.headers
