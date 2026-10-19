"""Cadastro com senha: verificação obrigatória e resposta que não revela quem é cliente."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from src.extensions import db
from src.integrations.brasilapi import ConsultaCnpj
from src.models import Agency, AuthToken, User
from src.services import cadastro_service

REGISTRO = {
    "name": "Marina Costa", "email": "nova@agencia.com.br",
    "password": "café com pão de queijo", "agency_name": "Agência Nova",
    "cnpj": "19.131.243/0001-97", "accept_terms": True,
}


@pytest.fixture()
def limpo(app):
    def _limpar():
        with app.app_context():
            db.session.query(AuthToken).delete()
            for agencia in db.session.scalars(select(Agency).where(Agency.name.like("Agência Nova%"))):
                db.session.delete(agencia)
            db.session.commit()
    _limpar()
    yield
    _limpar()


def _token(msg) -> str:
    link = re.search(r"https?://\S+", msg.texto).group(0)
    return parse_qs(urlparse(link).query)["token"][0]


def _registrar(client, **mudancas):
    return client.post("/api/v1/auth/register", json={**REGISTRO, **mudancas})


def _total_com_email(email: str) -> int:
    return db.session.scalar(select(func.count()).select_from(User).where(User.email == email))


def test_cria_admin_nao_verificado_e_manda_o_link(client, app, limpo, outbox):
    assert _registrar(client).status_code == 202
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "nova@agencia.com.br"))
        assert user.role.value == "admin" and user.has_password and not user.email_verified
        assert user.terms_accepted and user.agency.cnpj == "19.131.243/0001-97"
    assert outbox[-1].assunto == "Confirme seu e-mail — Lumina"


def test_email_ja_cadastrado_tem_a_mesma_resposta(client, app, limpo, outbox):
    primeira = _registrar(client)
    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == "nova@agencia.com.br"))
        user.email_verificado_em = user.created_at
        db.session.commit()
    segunda = _registrar(client, cnpj="11.222.333/0001-81", agency_name="Agência Nova Dois")
    assert (primeira.status_code, primeira.get_json()) == (segunda.status_code, segunda.get_json())
    assert outbox[-1].assunto == "Você já tem uma conta na Lumina"
    with app.app_context():
        assert _total_com_email("nova@agencia.com.br") == 1


def test_email_nao_verificado_recebe_link_novo(client, app, limpo, outbox):
    _registrar(client)
    with app.app_context():
        primeiro_id = db.session.scalar(select(User.id).where(User.email == "nova@agencia.com.br"))
    r = _registrar(client, password="outra senha bem comprida")
    assert r.status_code == 202
    assert [m.assunto for m in outbox] == ["Confirme seu e-mail — Lumina"] * 2
    with app.app_context():
        # O pendente com senha é substituído, não reaproveitado.
        assert _total_com_email("nova@agencia.com.br") == 1
        assert db.session.scalar(select(User.id).where(User.email == "nova@agencia.com.br")) != primeiro_id
        assert db.session.scalar(select(func.count()).select_from(Agency).where(Agency.name == "Agência Nova")) == 1


def test_segundo_cadastro_pendente_fica_com_a_senha_de_quem_confirmou(client, limpo, outbox):
    _registrar(client, password="senha do atacante aqui")
    _registrar(client, password="senha da vitima legitima")
    r = client.post("/api/v1/auth/verify-email", json={"token": _token(outbox[-1])})
    assert r.status_code == 200
    entrar = lambda senha: client.post(  # noqa: E731
        "/api/v1/auth/login", json={"email": "nova@agencia.com.br", "password": senha})
    assert entrar("senha da vitima legitima").status_code == 200
    assert entrar("senha do atacante aqui").status_code == 401


def test_convite_sem_senha_so_recebe_o_link_de_novo(client, app, limpo, outbox):
    with app.app_context():
        agencia = Agency(name="Agência Nova Convite", cnpj="11.222.333/0001-81", plan=None)
        user = User(email="nova@agencia.com.br", name="Convidada", password_hash=None,
                    email_verificado_em=None, agency=agencia)
        db.session.add_all([agencia, user])
        db.session.commit()
        user_id, agencia_id = user.id, agencia.id
    assert _registrar(client).status_code == 202
    assert [m.assunto for m in outbox] == ["Confirme seu e-mail — Lumina"]
    with app.app_context():
        assert db.session.get(User, user_id) is not None
        assert db.session.get(Agency, agencia_id) is not None


def test_cnpj_em_uso_nao_cria_e_avisa_por_email(client, app, limpo, outbox):
    _registrar(client)
    r = _registrar(client, email="outra@agencia.com.br")
    assert r.status_code == 202
    assert outbox[-1].assunto == "Este CNPJ já tem conta na Lumina"
    with app.app_context():
        assert _total_com_email("outra@agencia.com.br") == 0


def test_caixa_diferente_e_o_mesmo_email(client, app, limpo):
    _registrar(client, email="Nova@Agencia.COM.br")
    _registrar(client)
    with app.app_context():
        assert _total_com_email("nova@agencia.com.br") == 1


def test_campos_invalidos_voltam_por_campo(client, limpo):
    r = _registrar(client, name="Marina2", password="curta", cnpj="19.131.243/0001-90",
                   agency_name="!!!", accept_terms=False)
    assert r.status_code == 422
    campos = {f["field"] for f in r.get_json()["error"]["details"]["fields"]}
    assert campos == {"name", "password", "cnpj", "agency_name", "accept_terms"}


def test_senha_com_o_email_e_recusada(client, limpo):
    r = _registrar(client, password="nova@agencia é minha senha")
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["fields"][0]["field"] == "password"


def test_papel_nao_e_aceito_no_cadastro(client, limpo):
    assert _registrar(client, role="viewer").status_code == 422


def _receita_baixada(monkeypatch):
    monkeypatch.setattr(cadastro_service, "consultar_cnpj",
                        lambda cnpj: ConsultaCnpj(True, "X LTDA", "BAIXADA", True))


def test_cnpj_baixado_e_recusado(client, limpo, monkeypatch):
    _receita_baixada(monkeypatch)
    r = _registrar(client)
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["fields"][0]["type"] == "cnpj_inactive"


def test_cnpj_baixado_e_recusado_tambem_para_email_existente(client, limpo, monkeypatch):
    _registrar(client)
    _receita_baixada(monkeypatch)
    assert _registrar(client).status_code == 422


def test_link_confirma_e_ja_entra(client, app, limpo, outbox):
    _registrar(client)
    r = client.post("/api/v1/auth/verify-email", json={"token": _token(outbox[-1])})
    assert r.status_code == 200 and r.get_json()["data"]["tokens"]["access_token"]
    with app.app_context():
        assert db.session.scalar(select(User).where(User.email == "nova@agencia.com.br")).email_verified


def test_link_usado_duas_vezes(client, limpo, outbox):
    _registrar(client)
    token = _token(outbox[-1])
    client.post("/api/v1/auth/verify-email", json={"token": token})
    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "verification_token_invalid"


def test_reenvio_responde_igual_para_quem_existe_e_quem_nao(client, limpo, outbox):
    _registrar(client)
    outbox.clear()
    existe = client.post("/api/v1/auth/resend-verification", json={"email": "nova@agencia.com.br"})
    nao_existe = client.post("/api/v1/auth/resend-verification", json={"email": "ninguem@x.com"})
    assert (existe.status_code, existe.get_json()) == (nao_existe.status_code, nao_existe.get_json())
    assert len(outbox) == 1


def test_limite_de_cadastro_por_email(client, limpo):
    for _ in range(3):
        assert _registrar(client).status_code == 202
    assert _registrar(client).status_code == 429


def test_erro_de_validacao_nao_gasta_o_limite(client, limpo):
    for _ in range(5):
        _registrar(client, name="Marina2")
    assert _registrar(client).status_code == 202
