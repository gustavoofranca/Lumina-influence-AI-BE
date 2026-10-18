"""Login Google com contas de senha, comando de admin e limpeza de cadastros abandonados."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.extensions import db
from src.integrations.base_oauth import OAuthUserInfo
from src.integrations.google_oauth import GoogleOAuthClient
from src.jobs.cleanup_expired_tokens import run_cleanup_expired_tokens
from src.models import Agency, AuthToken, FinalidadeToken, User, UserRole
from src.utils.senha import conferir, gerar_hash

NOVA = "nova senha bem comprida"


@pytest.fixture()
def google(monkeypatch):
    def configurar(email, nome="Vítima Real"):
        monkeypatch.setattr(GoogleOAuthClient, "exchange_code",
                            lambda self, *, code, redirect_uri: {"access_token": "x"})
        monkeypatch.setattr(GoogleOAuthClient, "fetch_user_info", lambda self, token: OAuthUserInfo(
            provider="google", oauth_id="google-sub-1", email=email, name=nome, avatar_url=None))
    return configurar


def _login_google(client):
    r = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    return client.get(f"/api/v1/auth/google/callback?code=abc&state={state}")


def _cadastro_pendente(app, email, *, dias_atras=0, nome_agencia="Agência Pendente"):
    with app.app_context():
        agencia = Agency(name=nome_agencia, cnpj="19.131.243/0001-97")
        user = User(email=email, name="Quem Cadastrou", role=UserRole.ADMIN, agency=agencia,
                    password_hash=gerar_hash("senha que o atacante escolheu"))
        db.session.add_all([agencia, user])
        db.session.commit()
        if dias_atras:
            user.created_at = datetime.now(timezone.utc) - timedelta(days=dias_atras)
            db.session.commit()
        return user.id, agencia.id


def _apagar(app, *agency_ids):
    with app.app_context():
        for agency_id in agency_ids:
            agencia = db.session.get(Agency, agency_id)
            if agencia is not None:
                db.session.delete(agencia)
        db.session.commit()


# ---------------------------------------------------------------- Google
def test_google_descarta_cadastro_por_senha_nao_verificado(client, app, google):
    """Pré-sequestro de conta: alguém cadastra o e-mail da vítima com uma senha que só ele
    sabe, e a vítima depois entra pelo Google. A conta não pode chegar a ela com a senha dele."""
    _, agencia_do_atacante = _cadastro_pendente(app, "vitima@agencia.com.br",
                                                nome_agencia="Agência do Atacante")
    google("Vitima@Agencia.com.br")
    r = _login_google(client)
    try:
        assert r.status_code == 200 and r.get_json()["data"]["new_agency"] is True
        with app.app_context():
            user = db.session.scalar(select(User).where(User.email == "vitima@agencia.com.br"))
            assert user.password_hash is None and user.email_verified
            assert db.session.get(Agency, agencia_do_atacante) is None
    finally:
        with app.app_context():
            user = db.session.scalar(select(User).where(User.email == "vitima@agencia.com.br"))
            agency_id = user.agency_id if user else None
        _apagar(app, agency_id, agencia_do_atacante)


def test_google_cria_conta_com_email_minusculo_e_verificado(client, app, google):
    google("Nova.Pessoa@Agencia.com.br")
    _login_google(client)
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "nova.pessoa@agencia.com.br"))
        assert user is not None and user.email_verified
        agency_id = user.agency_id
    _apagar(app, agency_id)


# ---------------------------------------------------------------- comando
def _set_password(app, email, senha):
    return app.test_cli_runner().invoke(args=["users", "set-password", email], input=f"{senha}\n{senha}\n")


def test_comando_define_a_senha_e_verifica_o_email(client, app, conta_com_senha):
    with app.app_context():
        db.session.get(User, conta_com_senha.id).email_verificado_em = None
        db.session.commit()
    resultado = _set_password(app, "Conta@Agencia.com.br", NOVA)
    assert resultado.exit_code == 0, resultado.output
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        assert conferir(NOVA, user.password_hash) and user.email_verified


def test_comando_recusa_senha_fraca(app, conta_com_senha):
    resultado = _set_password(app, conta_com_senha.email, "curta")
    assert resultado.exit_code == 1 and "pelo menos 12" in resultado.output


def test_comando_recusa_email_desconhecido(app):
    resultado = _set_password(app, "ninguem@agencia.com.br", NOVA)
    assert resultado.exit_code == 1 and "não encontrado" in resultado.output


# ---------------------------------------------------------------- limpeza
def test_limpeza_apaga_cadastro_abandonado_ha_mais_de_7_dias(app):
    _, velho = _cadastro_pendente(app, "velho@agencia.com.br", dias_atras=8)
    with app.app_context():
        resultado = run_cleanup_expired_tokens()
        assert resultado["unverified_accounts_purged"] == 1
        assert db.session.get(Agency, velho) is None


def test_limpeza_mantem_cadastro_recente_e_conta_verificada(app, conta_com_senha):
    _, recente = _cadastro_pendente(app, "recente@agencia.com.br", dias_atras=6)
    try:
        with app.app_context():
            assert run_cleanup_expired_tokens()["unverified_accounts_purged"] == 0
            assert db.session.get(Agency, recente) is not None
            assert db.session.get(User, conta_com_senha.id) is not None
    finally:
        _apagar(app, recente)


def test_limpeza_apaga_tokens_gastos(app, conta_com_senha):
    with app.app_context():
        db.session.add(AuthToken(
            user_id=conta_com_senha.id, finalidade=FinalidadeToken.REDEFINIR_SENHA,
            token_hash="b" * 64, expira_em=datetime.now(timezone.utc) - timedelta(days=2),
        ))
        db.session.commit()
        assert run_cleanup_expired_tokens()["auth_tokens_purged"] == 1
