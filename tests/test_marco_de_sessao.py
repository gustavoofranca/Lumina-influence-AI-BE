"""Marco de sessão: token emitido antes de trocar a senha deixa de valer."""
from __future__ import annotations

import time

from src.extensions import db
from src.models import User
from src.services.auth_service import concluir_login, invalidar_sessoes
from src.utils.jwt_utils import encode_token, issue_token_pair

ME = "/api/v1/auth/me"


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_concluir_login_devolve_usuario_agencia_e_tokens(app, conta_com_senha):
    with app.test_request_context():
        dados = concluir_login(db.session.get(User, conta_com_senha.id))
    assert set(dados) == {"user", "agency", "tokens"}
    assert dados["tokens"]["access_token"] and dados["tokens"]["refresh_token"]


def test_token_anterior_ao_marco_e_recusado(client, app, conta_com_senha):
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        antigo = encode_token(token_type="access", user_id=user.id, extra={"iat": int(time.time()) - 60})
        invalidar_sessoes(user)
        db.session.commit()
    r = client.get(ME, headers=_h(antigo))
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "token_revoked"


def test_token_emitido_depois_do_marco_vale(client, app, conta_com_senha):
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        invalidar_sessoes(user)
        db.session.commit()
        novo = issue_token_pair(user)["access_token"]
    assert client.get(ME, headers=_h(novo)).status_code == 200


def test_refresh_tambem_respeita_o_marco(client, app, conta_com_senha):
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        refresh = encode_token(token_type="refresh", user_id=user.id, extra={"iat": int(time.time()) - 60})
        invalidar_sessoes(user)
        db.session.commit()
    r = client.post("/api/v1/auth/refresh", headers=_h(refresh))
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "token_revoked"


def test_sem_marco_token_antigo_continua_valendo(client, app, conta_com_senha):
    with app.app_context():
        antigo = encode_token(token_type="access", user_id=conta_com_senha.id,
                              extra={"iat": int(time.time()) - 60})
    assert client.get(ME, headers=_h(antigo)).status_code == 200
