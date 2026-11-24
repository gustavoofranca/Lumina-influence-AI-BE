"""Validação de campos de entrada — o que a varredura de 15/10/2026 achou.

Na avaliação, o professor tentou quebrar o cadastro de campanha. A varredura que
veio em seguida mandou 309 entradas hostis às 21 rotas que gravam dado e achou
três famílias de problema:

1. **Erro 500.** Byte nulo em qualquer texto, número acima de int64 e `null`
   explícito num campo obrigatório da edição passavam pelo schema e estouravam
   no banco.
2. **Lixo aceito.** Nome só de espaços, de caracteres invisíveis, com inversão
   de direção ou com marcação HTML; CNPJ qualquer; endereço de foto qualquer;
   datas no ano 1; relatório com período invertido.
3. **Erro mudo.** A recusa vinha em inglês, e a tela só mostrava "Erro de
   validação".

Cada teste aqui falhava antes da correção.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import Agency, Campaign, Influencer, SocialAccount, User, UserRole
from src.seed.seed_data import seed_clear, seed_run
from src.utils.jwt_utils import issue_token_pair


class Ctx:
    pass


@pytest.fixture()
def seeded(app):
    with app.app_context():
        seed_clear()
        seed_run()
        admin = db.session.scalar(select(User).where(User.role == UserRole.ADMIN))
        c = Ctx()
        c.header = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.user_id = str(admin.id)
        c.agency_id = str(admin.agency_id)
        c.influencer_id = str(db.session.scalar(select(Influencer)).id)
        c.campaign_id = str(db.session.scalar(select(Campaign)).id)
        c.account_id = str(db.session.scalar(select(SocialAccount)).id)
        yield c
        seed_clear()


CAMPANHA = {"brand_name": "Marca", "period_start": "2026-10-01", "period_end": "2026-10-31"}
RELATORIO = {"title": "Relatório", "period_start": "2026-10-01", "period_end": "2026-10-31"}


def campos_com_erro(resp) -> dict[str, str]:
    detalhes = resp.get_json()["error"]["details"]
    return {f["field"]: f["message"] for f in detalhes.get("fields", [])}


# --------------------------------------------------------------------------
# 1. Nada de erro 500
# --------------------------------------------------------------------------
TEXTO_COM_BYTE_NULO = [
    ("post", "/campaigns", CAMPANHA, "brand_name"),
    ("post", "/campaigns", CAMPANHA, "title"),
    ("post", "/influencers", {"display_name": "Nome"}, "display_name"),
    ("post", "/influencers", {"display_name": "Nome"}, "niche"),
    ("post", "/influencers", {"display_name": "Nome"}, "bio"),
    ("patch", "/agencies/{agency_id}", {}, "name"),
    ("patch", "/users/{user_id}", {}, "name"),
]


@pytest.mark.parametrize("metodo,rota,base,campo", TEXTO_COM_BYTE_NULO)
def test_byte_nulo_e_recusado_com_422(client, seeded, metodo, rota, base, campo):
    url = "/api/v1" + rota.format(**vars(seeded))
    r = getattr(client, metodo)(url, json={**base, campo: "abc\x00def"}, headers=seeded.header)
    assert r.status_code == 422
    assert campo in campos_com_erro(r)


@pytest.mark.parametrize("metodo,rota,campo", [
    ("post", "/campaigns", "budget_brl_cents"),
    ("patch", "/campaigns/{campaign_id}", "budget_brl_cents"),
    ("patch", "/social-accounts/{account_id}", "follower_count"),
])
def test_numero_acima_do_teto_e_recusado(client, seeded, metodo, rota, campo):
    base = CAMPANHA if metodo == "post" else {}
    url = "/api/v1" + rota.format(**vars(seeded))
    r = getattr(client, metodo)(url, json={**base, campo: 2**63}, headers=seeded.header)
    assert r.status_code == 422
    assert campo in campos_com_erro(r)


def test_cache_de_participante_acima_do_teto_e_recusado(client, seeded):
    corpo = {**CAMPANHA, "participants": [{"influencer_id": seeded.influencer_id, "fee_brl_cents": 2**63}]}
    r = client.post("/api/v1/campaigns", json=corpo, headers=seeded.header)
    assert r.status_code == 422


@pytest.mark.parametrize("rota,campo", [
    ("/campaigns/{campaign_id}", "brand_name"),
    ("/campaigns/{campaign_id}", "budget_brl_cents"),
    ("/campaigns/{campaign_id}", "period_end"),
    ("/influencers/{influencer_id}", "display_name"),
    ("/social-accounts/{account_id}", "follower_count"),
    ("/agencies/{agency_id}", "name"),
    ("/users/{user_id}", "name"),
])
def test_null_em_campo_obrigatorio_da_edicao_e_recusado(client, seeded, rota, campo):
    url = "/api/v1" + rota.format(**vars(seeded))
    r = client.patch(url, json={campo: None}, headers=seeded.header)
    assert r.status_code == 422
    assert campos_com_erro(r)[campo] == "não pode ficar vazio"


# --------------------------------------------------------------------------
# 2. Conteúdo de texto
# --------------------------------------------------------------------------
LIXO_EM_NOME = {
    "so_espacos": "     ",
    "so_invisiveis": "\u200b\u200b\u200b",
    "inversao_de_direcao": "\u202eabc",
    "quebra_de_linha": "linha1\nlinha2",
    "marcacao_html": "<b>Marca</b>",
}
CAMPOS_DE_NOME = [
    ("post", "/campaigns", CAMPANHA, "brand_name"),
    ("patch", "/campaigns/{campaign_id}", {}, "brand_name"),
    ("post", "/influencers", {}, "display_name"),
    ("patch", "/agencies/{agency_id}", {}, "name"),
    ("patch", "/users/{user_id}", {}, "name"),
]
# O nicho é opcional: em branco vira nulo (ver o teste do título opcional), mas
# o conteúdo que não é branco segue a regra de nome.
LIXO_EM_NOME_OPCIONAL = {k: v for k, v in LIXO_EM_NOME.items() if k not in ("so_espacos", "so_invisiveis")}


@pytest.mark.parametrize("carga", LIXO_EM_NOME.values(), ids=LIXO_EM_NOME.keys())
@pytest.mark.parametrize("metodo,rota,base,campo", CAMPOS_DE_NOME)
def test_nome_recusa_lixo(client, seeded, metodo, rota, base, campo, carga):
    url = "/api/v1" + rota.format(**vars(seeded))
    r = getattr(client, metodo)(url, json={**base, campo: carga}, headers=seeded.header)
    assert r.status_code == 422, r.get_json()
    assert campo in campos_com_erro(r)


@pytest.mark.parametrize("carga", LIXO_EM_NOME_OPCIONAL.values(), ids=LIXO_EM_NOME_OPCIONAL.keys())
def test_nicho_recusa_o_mesmo_lixo_que_o_nome(client, seeded, carga):
    r = client.post("/api/v1/influencers", json={"display_name": "Nome", "niche": carga}, headers=seeded.header)
    assert r.status_code == 422
    assert "niche" in campos_com_erro(r)


@pytest.mark.parametrize("carga", ["     ", "\u200b\u200b"], ids=["so_espacos", "so_invisiveis"])
def test_nicho_em_branco_vira_nulo(client, seeded, carga):
    r = client.post("/api/v1/influencers", json={"display_name": "Nome", "niche": carga}, headers=seeded.header)
    assert r.status_code == 201
    assert r.get_json()["data"]["niche"] is None


def test_nome_perde_os_espacos_das_pontas(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "brand_name": "  Marca X  "}, headers=seeded.header)
    assert r.status_code == 201
    assert r.get_json()["data"]["brand_name"] == "Marca X"


def test_titulo_aceita_pontuacao_que_o_nome_recusa(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "title": "Campanha <Verão> 2026"}, headers=seeded.header)
    assert r.status_code == 201


def test_texto_opcional_em_branco_vira_nulo(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "title": "   "}, headers=seeded.header)
    assert r.status_code == 201
    assert r.get_json()["data"]["title"] is None


def test_bio_aceita_quebra_de_linha_mas_nao_controle(client, seeded):
    ok = client.post("/api/v1/influencers", json={"display_name": "Nome", "bio": "linha 1\nlinha 2"}, headers=seeded.header)
    assert ok.status_code == 201
    assert ok.get_json()["data"]["bio"] == "linha 1\nlinha 2"

    ruim = client.post("/api/v1/influencers", json={"display_name": "Nome", "bio": "a\x07b"}, headers=seeded.header)
    assert ruim.status_code == 422


# --------------------------------------------------------------------------
# 3. Números e datas
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["100", True, -1, 10.5], ids=["texto", "booleano", "negativo", "decimal"])
def test_orcamento_so_aceita_inteiro_nao_negativo(client, seeded, valor):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "budget_brl_cents": valor}, headers=seeded.header)
    assert r.status_code == 422
    assert "budget_brl_cents" in campos_com_erro(r)


@pytest.mark.parametrize("data", ["0001-01-01", "9999-12-31", "1999-12-31", "2101-01-01"])
def test_data_fora_da_faixa_e_recusada(client, seeded, data):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "period_start": data}, headers=seeded.header)
    assert r.status_code == 422
    assert "period_start" in campos_com_erro(r)


def test_campanha_com_periodo_invertido_aponta_o_campo_do_fim(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "period_end": "2026-09-01"}, headers=seeded.header)
    assert r.status_code == 422
    assert "period_end" in campos_com_erro(r)


def test_relatorio_com_periodo_invertido_e_recusado(client, seeded):
    corpo = {**RELATORIO, "campaign_id": seeded.campaign_id, "period_end": "2026-01-01"}
    r = client.post("/api/v1/reports/preview", json=corpo, headers=seeded.header)
    assert r.status_code == 422
    assert "period_end" in campos_com_erro(r)


@pytest.mark.parametrize("secoes", [[], ["kpis", "kpis"]], ids=["vazia", "repetida"])
def test_relatorio_exige_secoes_distintas(client, seeded, secoes):
    corpo = {**RELATORIO, "campaign_id": seeded.campaign_id, "sections": secoes}
    r = client.post("/api/v1/reports/preview", json=corpo, headers=seeded.header)
    assert r.status_code == 422
    assert "sections" in campos_com_erro(r)


def test_periodo_invalido_no_painel_e_recusado(client, seeded):
    r = client.get("/api/v1/dashboard/overview?period=xyz", headers=seeded.header)
    assert r.status_code == 422


# --------------------------------------------------------------------------
# 4. CNPJ e endereço de foto
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cnpj", ["abc", "123", "11.222.333/0001-80", "00.000.000/0000-00"],
                         ids=["letras", "curto", "digito_errado", "repetido"])
def test_cnpj_invalido_e_recusado(client, seeded, cnpj):
    r = client.patch(f"/api/v1/agencies/{seeded.agency_id}", json={"cnpj": cnpj}, headers=seeded.header)
    assert r.status_code == 422
    assert "cnpj" in campos_com_erro(r)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-81", "11222333000181"], ids=["com_mascara", "so_digitos"])
def test_cnpj_valido_e_gravado_com_mascara(client, seeded, cnpj):
    r = client.patch(f"/api/v1/agencies/{seeded.agency_id}", json={"cnpj": cnpj}, headers=seeded.header)
    assert r.status_code == 200
    assert r.get_json()["data"]["cnpj"] == "11.222.333/0001-81"


def test_cnpj_antigo_invalido_nao_trava_a_edicao_do_nome(client, seeded, app):
    """A tela de Agência reenvia o CNPJ a cada salvamento.

    Um CNPJ gravado antes desta regra, com dígito errado, não pode impedir a
    pessoa de mudar o nome da agência: o dígito só é conferido quando o CNPJ
    muda. Em produção a agência principal tem exatamente esse caso.
    """
    with app.app_context():
        agencia = db.session.get(Agency, __import__("uuid").UUID(seeded.agency_id))
        agencia.cnpj = "12.345.678/0001-90"
        db.session.commit()

    r = client.patch(
        f"/api/v1/agencies/{seeded.agency_id}",
        json={"name": "Agência Renomeada", "cnpj": "12.345.678/0001-90"},
        headers=seeded.header,
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["name"] == "Agência Renomeada"


@pytest.mark.parametrize("vazio", ["", None], ids=["texto-vazio", "nulo"])
def test_cnpj_existente_nao_pode_ser_removido(client, seeded, vazio):
    r = client.patch(f"/api/v1/agencies/{seeded.agency_id}", json={"cnpj": vazio}, headers=seeded.header)
    assert r.status_code == 422
    campo = r.get_json()["error"]["details"]["fields"][0]
    assert (campo["field"], campo["type"], campo["message"]) == (
        "cnpj", "cnpj_required", "o CNPJ não pode ser removido",
    )


def test_agencia_sem_cnpj_aceita_cnpj_em_branco(client, seeded, app):
    with app.app_context():
        db.session.get(Agency, __import__("uuid").UUID(seeded.agency_id)).cnpj = None
        db.session.commit()
    r = client.patch(f"/api/v1/agencies/{seeded.agency_id}", json={"cnpj": ""}, headers=seeded.header)
    assert r.status_code == 200
    assert r.get_json()["data"]["cnpj"] is None


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,<script>x</script>", "http://exemplo.com/a.png", "nao sou url",
], ids=["javascript", "data", "http", "texto"])
def test_foto_so_aceita_endereco_https(client, seeded, url):
    r = client.patch(f"/api/v1/users/{seeded.user_id}", json={"avatar_url": url}, headers=seeded.header)
    assert r.status_code == 422
    assert "avatar_url" in campos_com_erro(r)


def test_foto_https_e_aceita(client, seeded):
    r = client.patch(f"/api/v1/users/{seeded.user_id}", json={"avatar_url": "https://exemplo.com/a.png"},
                     headers=seeded.header)
    assert r.status_code == 200


# --------------------------------------------------------------------------
# 5. A recusa diz o que houve, em português
# --------------------------------------------------------------------------
def test_mensagem_de_erro_vem_em_portugues_e_nomeia_o_campo(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "brand_name": "a" * 161}, headers=seeded.header)
    assert r.status_code == 422
    erro = r.get_json()["error"]
    assert erro["message"] == "Marca: deve ter no máximo 160 caracteres"
    assert campos_com_erro(r)["brand_name"] == "deve ter no máximo 160 caracteres"


def test_varios_erros_pedem_para_corrigir_os_campos(client, seeded):
    r = client.post("/api/v1/campaigns", json={"brand_name": "", "period_start": "x", "period_end": "y"},
                    headers=seeded.header)
    assert r.status_code == 422
    assert r.get_json()["error"]["message"] == "Corrija os campos indicados"
    assert set(campos_com_erro(r)) >= {"brand_name", "period_start", "period_end"}


def test_lista_de_opcoes_sai_em_portugues(client, seeded):
    r = client.post("/api/v1/campaigns", json={**CAMPANHA, "status": "xyz"}, headers=seeded.header)
    assert r.status_code == 422
    mensagem = campos_com_erro(r)["status"]
    assert " ou " in mensagem and " or " not in mensagem


def test_email_invalido_tem_mensagem_em_portugues(client, seeded):
    r = client.post("/api/v1/users", json={"name": "Fulano", "email": "fulano"}, headers=seeded.header)
    assert r.status_code == 422
    assert campos_com_erro(r)["email"] == "e-mail inválido"
