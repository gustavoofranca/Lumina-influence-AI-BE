"""Login por senha e o ciclo de vida da senha."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from src.extensions import db
from src.models import AuthToken, User
from src.services import senha_service
from src.utils.jwt_utils import encode_token, issue_token_pair
from src.utils.senha import conferir

LOGIN, ME = "/api/v1/auth/login", "/api/v1/auth/me"
NOVA = "nova senha bem comprida"


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _entrar(client, email, senha):
    return client.post(LOGIN, json={"email": email, "password": senha})


def _credenciais_invalidas(r) -> bool:
    return r.status_code == 401 and r.get_json()["error"] == {
        "code": "invalid_credentials", "message": "E-mail ou senha incorretos.", "details": {},
    }


def _token(msg) -> str:
    link = re.search(r"https?://\S+", msg.texto).group(0)
    return parse_qs(urlparse(link).query)["token"][0]


def _mudar(app, conta, **campos):
    with app.app_context():
        user = db.session.get(User, conta.id)
        for nome, valor in campos.items():
            setattr(user, nome, valor)
        db.session.commit()


def _token_antigo(conta) -> str:
    """Access token emitido um minuto atrás — o que um invasor teria guardado."""
    return encode_token(token_type="access", user_id=conta.id, extra={"iat": int(time.time()) - 60})


# ---------------------------------------------------------------- login
def test_entra_com_email_e_senha(client, conta_com_senha):
    r = _entrar(client, conta_com_senha.email, conta_com_senha.senha)
    assert r.status_code == 200
    assert client.get(ME, headers=_h(r.get_json()["data"]["tokens"]["access_token"])).status_code == 200


def test_email_com_maiusculas_e_espacos_entra(client, conta_com_senha):
    assert _entrar(client, "  Conta@Agencia.COM.br ", conta_com_senha.senha).status_code == 200


def test_senha_errada(client, conta_com_senha):
    assert _credenciais_invalidas(_entrar(client, conta_com_senha.email, "senha errada mesmo"))


def test_email_inexistente_responde_igual(client, conta_com_senha):
    assert _credenciais_invalidas(_entrar(client, "ninguem@agencia.com.br", conta_com_senha.senha))


def test_conta_so_google_responde_igual(client, app, conta_com_senha):
    _mudar(app, conta_com_senha, password_hash=None)
    assert _credenciais_invalidas(_entrar(client, conta_com_senha.email, conta_com_senha.senha))


def test_conta_excluida_responde_igual(client, app, conta_com_senha):
    _mudar(app, conta_com_senha, deleted_at=datetime.now(timezone.utc))
    assert _credenciais_invalidas(_entrar(client, conta_com_senha.email, conta_com_senha.senha))


def test_nao_verificada_so_ouve_403_com_a_senha_certa(client, app, conta_com_senha):
    _mudar(app, conta_com_senha, email_verificado_em=None)
    r = _entrar(client, conta_com_senha.email, conta_com_senha.senha)
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "email_not_verified"
    assert _credenciais_invalidas(_entrar(client, conta_com_senha.email, "senha errada mesmo"))


def test_email_inexistente_gasta_o_tempo_de_um_hash(client, monkeypatch):
    chamadas = []
    monkeypatch.setattr(senha_service, "conferir_contra_hash_ficticio", chamadas.append)
    _entrar(client, "ninguem@agencia.com.br", "qualquer senha longa")
    assert chamadas == ["qualquer senha longa"]


def test_cinco_falhas_bloqueiam_mesmo_variando_a_caixa(client, conta_com_senha):
    for email in ["conta@agencia.com.br", "CONTA@agencia.com.br", "Conta@Agencia.com.br",
                  "conta@AGENCIA.com.br", "cOnTa@agencia.com.br"]:
        _entrar(client, email, "senha errada mesmo")
    assert _entrar(client, conta_com_senha.email, conta_com_senha.senha).status_code == 429


def test_login_certo_zera_as_falhas_do_email(client, conta_com_senha):
    for _ in range(4):
        _entrar(client, conta_com_senha.email, "senha errada mesmo")
    assert _entrar(client, conta_com_senha.email, conta_com_senha.senha).status_code == 200
    for _ in range(4):
        _entrar(client, conta_com_senha.email, "senha errada mesmo")
    assert _entrar(client, conta_com_senha.email, conta_com_senha.senha).status_code == 200


def test_hash_antigo_e_refeito_no_login(client, app, conta_com_senha, monkeypatch):
    with app.app_context():
        antes = db.session.get(User, conta_com_senha.id).password_hash
    monkeypatch.setattr(senha_service, "precisa_rehash", lambda h: True)
    _entrar(client, conta_com_senha.email, conta_com_senha.senha)
    with app.app_context():
        depois = db.session.get(User, conta_com_senha.id).password_hash
    assert depois != antes and conferir(conta_com_senha.senha, depois)


def test_opcoes(client):
    assert client.get("/api/v1/auth/options").get_json()["data"] == {"dev_login": True, "google": True}


# ---------------------------------------------------------------- esqueci e redefinir
def _pedir_link(client, email):
    return client.post("/api/v1/auth/forgot-password", json={"email": email})


def test_esqueci_responde_igual_e_so_manda_para_quem_existe(client, conta_com_senha, outbox):
    existe = _pedir_link(client, conta_com_senha.email)
    nao_existe = _pedir_link(client, "ninguem@agencia.com.br")
    assert (existe.status_code, existe.get_json()) == (nao_existe.status_code, nao_existe.get_json())
    assert [m.assunto for m in outbox] == ["Redefinir sua senha — Lumina"]


def test_conta_so_google_recebe_link_para_definir_senha(client, app, conta_com_senha, outbox):
    _mudar(app, conta_com_senha, password_hash=None)
    _pedir_link(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/reset-password", json={"token": _token(outbox[-1]), "password": NOVA})
    assert r.status_code == 204
    assert _entrar(client, conta_com_senha.email, NOVA).status_code == 200


def test_redefinir_troca_a_senha_e_derruba_as_sessoes(client, conta_com_senha, outbox):
    antigo = _token_antigo(conta_com_senha)
    _pedir_link(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/reset-password", json={"token": _token(outbox[-1]), "password": NOVA})
    assert r.status_code == 204
    assert client.get(ME, headers=_h(antigo)).get_json()["error"]["code"] == "token_revoked"
    assert _entrar(client, conta_com_senha.email, NOVA).status_code == 200
    assert _credenciais_invalidas(_entrar(client, conta_com_senha.email, conta_com_senha.senha))


def test_senha_fraca_na_redefinicao_nao_gasta_o_link(client, conta_com_senha, outbox):
    _pedir_link(client, conta_com_senha.email)
    token = _token(outbox[-1])
    fraca = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "curta"})
    assert fraca.status_code == 422
    assert fraca.get_json()["error"]["details"]["fields"][0]["field"] == "password"
    boa = client.post("/api/v1/auth/reset-password", json={"token": token, "password": NOVA})
    assert boa.status_code == 204


def test_senha_com_o_email_na_redefinicao(client, conta_com_senha, outbox):
    _pedir_link(client, conta_com_senha.email)
    r = client.post("/api/v1/auth/reset-password",
                    json={"token": _token(outbox[-1]), "password": "minha conta nova de novo"})
    assert r.status_code == 422


def test_link_de_redefinicao_reusado(client, conta_com_senha, outbox):
    _pedir_link(client, conta_com_senha.email)
    token = _token(outbox[-1])
    client.post("/api/v1/auth/reset-password", json={"token": token, "password": NOVA})
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "password": NOVA + "!"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "reset_token_invalid"


def test_link_de_redefinicao_vencido(client, app, conta_com_senha, outbox):
    _pedir_link(client, conta_com_senha.email)
    with app.app_context():
        registro = db.session.scalar(select(AuthToken).where(AuthToken.usado_em.is_(None)))
        registro.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    r = client.post("/api/v1/auth/reset-password", json={"token": _token(outbox[-1]), "password": NOVA})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "reset_token_expired"


# ---------------------------------------------------------------- trocar senha
TROCAR = "/api/v1/auth/change-password"


def _sessao(app, conta) -> str:
    with app.app_context():
        return issue_token_pair(db.session.get(User, conta.id))["access_token"]


def _campo(r) -> tuple[str, str]:
    campo = r.get_json()["error"]["details"]["fields"][0]
    return campo["field"], campo["type"]


def test_trocar_senha_devolve_sessao_nova_e_derruba_as_outras(client, app, conta_com_senha):
    antigo = _token_antigo(conta_com_senha)
    r = client.post(TROCAR, headers=_h(_sessao(app, conta_com_senha)),
                    json={"current_password": conta_com_senha.senha, "new_password": NOVA})
    assert r.status_code == 200
    novo = r.get_json()["data"]["tokens"]["access_token"]
    assert client.get(ME, headers=_h(novo)).status_code == 200
    assert client.get(ME, headers=_h(antigo)).get_json()["error"]["code"] == "token_revoked"


def test_senha_atual_errada_e_422_no_campo_e_nao_401(client, app, conta_com_senha):
    r = client.post(TROCAR, headers=_h(_sessao(app, conta_com_senha)),
                    json={"current_password": "senha errada mesmo", "new_password": NOVA})
    assert r.status_code == 422
    assert _campo(r) == ("current_password", "invalid_current_password")


def test_trocar_para_senha_fraca(client, app, conta_com_senha):
    r = client.post(TROCAR, headers=_h(_sessao(app, conta_com_senha)),
                    json={"current_password": conta_com_senha.senha, "new_password": "curta"})
    assert r.status_code == 422 and _campo(r)[0] == "new_password"


def test_trocar_sem_ter_senha(client, app, conta_com_senha):
    _mudar(app, conta_com_senha, password_hash=None)
    r = client.post(TROCAR, headers=_h(_sessao(app, conta_com_senha)),
                    json={"current_password": "qualquer", "new_password": NOVA})
    assert r.status_code == 422 and _campo(r) == ("current_password", "no_password")


# ---------------------------------------------------------------- termos
def test_aceitar_termos(client, app, conta_com_senha):
    r = client.post("/api/v1/auth/accept-terms", headers=_h(_sessao(app, conta_com_senha)))
    assert r.status_code == 204
    with app.app_context():
        assert db.session.get(User, conta_com_senha.id).terms_accepted


def test_aceitar_termos_exige_login(client):
    assert client.post("/api/v1/auth/accept-terms").status_code == 401
