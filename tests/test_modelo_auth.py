"""Conta com senha e tokens de uso único no modelo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.extensions import db
from src.models import Agency, AuthToken, FinalidadeToken, User, UserRole
from src.utils.jwt_utils import issue_token_pair


def _conta(email="modelo@agencia.com.br", *, verificada=True):
    agencia = Agency(name="Agência Modelo", cnpj="11.222.333/0001-81")
    user = User(
        email=email, name="Modelo Teste", password_hash="$argon2id$fake",
        role=UserRole.ADMIN, agency=agencia,
        email_verificado_em=datetime.now(timezone.utc) if verificada else None,
    )
    db.session.add_all([agencia, user])
    db.session.commit()
    return agencia, user


def test_conta_so_com_senha_nao_tem_provedor(app):
    with app.app_context():
        agencia, user = _conta()
        try:
            assert user.oauth_provider is None and user.oauth_id is None
            assert user.has_password and user.email_verified and not user.terms_accepted
        finally:
            db.session.delete(agencia)
            db.session.commit()


def test_token_some_junto_com_o_usuario(app):
    with app.app_context():
        agencia, user = _conta()
        db.session.add(AuthToken(
            user_id=user.id, finalidade=FinalidadeToken.VERIFICAR_EMAIL,
            token_hash="a" * 64, expira_em=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.session.commit()
        db.session.delete(agencia)
        db.session.commit()
        assert db.session.scalar(select(AuthToken)) is None


def test_me_mostra_as_flags_e_nunca_o_hash(client, app):
    with app.app_context():
        agencia, user = _conta()
        # Capturado aqui: fora do contexto a sessão é removida e o objeto solta.
        agencia_id = agencia.id
        token = issue_token_pair(user)["access_token"]
    try:
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        dados = r.get_json()["data"]
        assert dados["user"]["has_password"] is True
        assert dados["user"]["email_verified"] is True
        assert dados["user"]["oauth_provider"] is None
        assert dados["agency"]["cnpj"] == "11.222.333/0001-81"
        assert "password_hash" not in r.get_data(as_text=True)
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Agency, agencia_id))
            db.session.commit()
