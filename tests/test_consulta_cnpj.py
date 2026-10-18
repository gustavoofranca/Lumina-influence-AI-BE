"""Consulta de CNPJ na BrasilAPI: só recusa situação impeditiva, nunca trava por falha."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from src.extensions import db
from src.integrations import brasilapi
from src.integrations.brasilapi import NAO_CONSULTADO, ConsultaCnpj, consultar_cnpj
from src.models import Agency, User
from src.utils.jwt_utils import issue_token_pair


class _Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo if corpo is not None else {}

    def json(self):
        if isinstance(self._corpo, Exception):
            raise self._corpo
        return self._corpo


ATIVA = _Resp(200, {
    "razao_social": "ACME MARKETING DIGITAL LTDA", "situacao_cadastral": 2,
    "descricao_situacao_cadastral": "ATIVA", "qsa": [{"nome_socio": "FULANO DE TAL"}],
})
BAIXADA = _Resp(200, {
    "razao_social": "ANTIGA LTDA", "situacao_cadastral": 8, "descricao_situacao_cadastral": "BAIXADA",
})


@pytest.fixture()
def receita(app, monkeypatch):
    monkeypatch.setitem(app.config, "CNPJ_CONSULTA_ENABLED", True)
    brasilapi.limpar_cache()
    ctx = SimpleNamespace(chamadas=[], respostas={})

    def falso_get(url, timeout, headers):
        ctx.chamadas.append(url)
        resposta = ctx.respostas.get(url.rsplit("/", 1)[1], _Resp(404))
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(brasilapi.requests, "get", falso_get)
    yield ctx
    brasilapi.limpar_cache()


def test_cnpj_ativo(app, receita):
    receita.respostas["11222333000181"] = ATIVA
    with app.app_context():
        c = consultar_cnpj("11.222.333/0001-81")
    assert c == ConsultaCnpj(True, "ACME MARKETING DIGITAL LTDA", "ATIVA", False)


def test_cnpj_baixado_e_impeditivo(app, receita):
    receita.respostas["11222333000181"] = BAIXADA
    with app.app_context():
        assert consultar_cnpj("11222333000181").impeditiva is True


def test_nao_encontrado_nao_impede(app, receita):
    with app.app_context():
        c = consultar_cnpj("12.ABC.345/01DE-35")
    assert c.encontrado is False and c.impeditiva is False


def test_timeout_nao_trava(app, receita):
    receita.respostas["11222333000181"] = requests.Timeout()
    with app.app_context():
        assert consultar_cnpj("11222333000181") == NAO_CONSULTADO


def test_erro_do_servico_nao_fica_em_cache(app, receita):
    receita.respostas["11222333000181"] = _Resp(500)
    with app.app_context():
        consultar_cnpj("11222333000181")
        consultar_cnpj("11222333000181")
    assert len(receita.chamadas) == 2


def test_resultado_fica_em_cache(app, receita):
    receita.respostas["11222333000181"] = ATIVA
    with app.app_context():
        consultar_cnpj("11222333000181")
        consultar_cnpj("11.222.333/0001-81")
    assert len(receita.chamadas) == 1


def test_entrada_fora_do_formato_nunca_chega_na_rede(app, receita):
    with app.app_context():
        assert consultar_cnpj("../../admin?x=1") == NAO_CONSULTADO
    assert receita.chamadas == []


def test_desligada_nao_consulta(app, receita, monkeypatch):
    monkeypatch.setitem(app.config, "CNPJ_CONSULTA_ENABLED", False)
    with app.app_context():
        assert consultar_cnpj("11222333000181") == NAO_CONSULTADO
    assert receita.chamadas == []


def test_endpoint_repassa_so_razao_social_e_situacao(client, receita):
    receita.respostas["11222333000181"] = ATIVA
    r = client.get("/api/v1/auth/cnpj/11222333000181")
    assert r.status_code == 200
    assert set(r.get_json()["data"]) == {"cnpj", "encontrado", "razao_social", "situacao", "impeditiva"}
    assert "FULANO" not in r.get_data(as_text=True)


def test_endpoint_recusa_dv_errado(client):
    r = client.get("/api/v1/auth/cnpj/11222333000180")
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["fields"][0]["field"] == "cnpj"


def test_endpoint_tem_limite_por_ip(client, receita):
    for _ in range(20):
        client.get("/api/v1/auth/cnpj/11222333000181")
    assert client.get("/api/v1/auth/cnpj/11222333000181").status_code == 429


def _admin_header(app, conta) -> dict:
    with app.app_context():
        token = issue_token_pair(db.session.get(User, conta.id))["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _tipo_do_erro(r) -> str:
    return r.get_json()["error"]["details"]["fields"][0]["type"]


def test_patch_da_agencia_recusa_cnpj_baixado(client, app, conta_com_senha, receita):
    receita.respostas["19131243000197"] = BAIXADA
    r = client.patch(f"/api/v1/agencies/{conta_com_senha.agency_id}",
                     json={"cnpj": "19.131.243/0001-97"}, headers=_admin_header(app, conta_com_senha))
    assert r.status_code == 422 and _tipo_do_erro(r) == "cnpj_inactive"


def test_patch_da_agencia_recusa_cnpj_de_outra_sem_dizer_de_quem(client, app, conta_com_senha):
    with app.app_context():
        outra = Agency(name="Outra Agência", cnpj="19.131.243/0001-97")
        db.session.add(outra)
        db.session.commit()
        outra_id = outra.id
    try:
        r = client.patch(f"/api/v1/agencies/{conta_com_senha.agency_id}",
                         json={"cnpj": "19131243000197"}, headers=_admin_header(app, conta_com_senha))
        assert r.status_code == 422 and _tipo_do_erro(r) == "cnpj_unavailable"
        assert "Outra Agência" not in r.get_data(as_text=True)
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Agency, outra_id))
            db.session.commit()


def test_corpo_que_nao_e_json_nao_trava(app, client, receita):
    receita.respostas["11222333000181"] = _Resp(200, ValueError("html"))
    with app.app_context():
        assert consultar_cnpj("11222333000181") == NAO_CONSULTADO
    assert client.get("/api/v1/auth/cnpj/11222333000181").status_code == 200


def test_json_que_nao_e_objeto_nao_trava(app, receita):
    receita.respostas["11222333000181"] = _Resp(200, [1, 2])
    with app.app_context():
        assert consultar_cnpj("11222333000181") == NAO_CONSULTADO


def test_situacao_como_texto_continua_impeditiva(app, receita):
    receita.respostas["11222333000181"] = _Resp(200, {"situacao_cadastral": "8",
                                                      "descricao_situacao_cadastral": "BAIXADA"})
    with app.app_context():
        c = consultar_cnpj("11222333000181")
    assert c.encontrado is True and c.impeditiva is True
