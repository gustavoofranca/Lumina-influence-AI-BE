"""Testes de CRUD da B4 — cobre cada recurso + isolamento entre agências."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.extensions import db
from src.models import (
    Agency,
    Campaign,
    CampaignStatus,
    Influencer,
    InfluencerStatus,
    Platform,
    Plan,
    SocialAccount,
    User,
    UserRole,
)
from src.models._enums import OAuthProvider
from src.utils.jwt_utils import issue_token_pair


# --------------------------------------------------------------------------
# Setup: duas agências isoladas
# --------------------------------------------------------------------------
class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        # Limpa tudo
        for model in (SocialAccount, Influencer, Campaign, User, Agency, Plan):
            db.session.query(model).delete()
        db.session.commit()

        plan = Plan(name="Agency", max_influencers=50, max_analyses_per_month=500, price_brl_cents=129700)
        db.session.add(plan)

        agency_a = Agency(name="Agência A", plan=plan)
        agency_b = Agency(name="Agência B")
        db.session.add_all([agency_a, agency_b])
        db.session.flush()

        def mk_user(email, role, agency):
            u = User(
                email=email,
                name=email.split("@")[0],
                oauth_provider=OAuthProvider.GOOGLE,
                oauth_id=f"oauth-{email}",
                role=role,
                agency=agency,
            )
            db.session.add(u)
            return u

        a_admin = mk_user("admin@a.com", UserRole.ADMIN, agency_a)
        a_member = mk_user("member@a.com", UserRole.MEMBER, agency_a)
        a_viewer = mk_user("viewer@a.com", UserRole.VIEWER, agency_a)
        b_admin = mk_user("admin@b.com", UserRole.ADMIN, agency_b)

        inf_a = Influencer(agency=agency_a, display_name="Influ A", niche="tech", status=InfluencerStatus.ACTIVE)
        inf_b = Influencer(agency=agency_b, display_name="Influ B", niche="food", status=InfluencerStatus.ACTIVE)
        db.session.add_all([inf_a, inf_b])
        db.session.flush()

        sa_a = SocialAccount(influencer=inf_a, platform=Platform.INSTAGRAM, handle="influa", follower_count=1000)
        db.session.add(sa_a)

        camp_a = Campaign(
            agency=agency_a, brand_name="Marca A", period_start=date(2026, 1, 1),
            period_end=date(2026, 2, 1), status=CampaignStatus.ACTIVE,
        )
        db.session.add(camp_a)
        db.session.commit()

        c = Ctx()
        c.plan_id = str(plan.id)
        c.agency_a_id = str(agency_a.id)
        c.agency_b_id = str(agency_b.id)
        c.inf_a_id = str(inf_a.id)
        c.inf_b_id = str(inf_b.id)
        c.sa_a_id = str(sa_a.id)
        c.camp_a_id = str(camp_a.id)
        c.h_a_admin = {"Authorization": f"Bearer {issue_token_pair(a_admin)['access_token']}"}
        c.h_a_member = {"Authorization": f"Bearer {issue_token_pair(a_member)['access_token']}"}
        c.h_a_viewer = {"Authorization": f"Bearer {issue_token_pair(a_viewer)['access_token']}"}
        c.h_b_admin = {"Authorization": f"Bearer {issue_token_pair(b_admin)['access_token']}"}
        yield c

        for model in (SocialAccount, Influencer, Campaign, User, Agency, Plan):
            db.session.query(model).delete()
        db.session.commit()


# --------------------------------------------------------------------------
# Plans (read-only)
# --------------------------------------------------------------------------
def test_plans_list(client, ctx):
    r = client.get("/api/v1/plans", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert len(r.get_json()["data"]) >= 1


def test_plans_require_auth(client, ctx):
    r = client.get("/api/v1/plans")
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Influencers
# --------------------------------------------------------------------------
def test_list_influencers_scoped_to_agency(client, ctx):
    r = client.get("/api/v1/influencers", headers=ctx.h_a_admin)
    assert r.status_code == 200
    body = r.get_json()
    names = [i["display_name"] for i in body["data"]]
    assert "Influ A" in names
    assert "Influ B" not in names  # isolamento
    assert "pagination" in body["meta"]


def test_get_other_agency_influencer_returns_404(client, ctx):
    r = client.get(f"/api/v1/influencers/{ctx.inf_b_id}", headers=ctx.h_a_admin)
    assert r.status_code == 404


def test_create_influencer(client, ctx):
    r = client.post(
        "/api/v1/influencers",
        headers=ctx.h_a_admin,
        json={"display_name": "Nova Influ", "niche": "games"},
    )
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["display_name"] == "Nova Influ"
    assert data["agency_id"] == ctx.agency_a_id
    assert data["status"] == "active"


def test_create_influencer_viewer_forbidden(client, ctx):
    r = client.post(
        "/api/v1/influencers", headers=ctx.h_a_viewer, json={"display_name": "X"}
    )
    assert r.status_code == 403


def test_update_influencer(client, ctx):
    r = client.patch(
        f"/api/v1/influencers/{ctx.inf_a_id}",
        headers=ctx.h_a_member,
        json={"niche": "lifestyle", "status": "paused"},
    )
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["niche"] == "lifestyle"
    assert data["status"] == "paused"


def test_update_other_agency_influencer_404(client, ctx):
    r = client.patch(
        f"/api/v1/influencers/{ctx.inf_b_id}", headers=ctx.h_a_admin, json={"niche": "x"}
    )
    assert r.status_code == 404


def test_delete_influencer(client, ctx):
    r = client.delete(f"/api/v1/influencers/{ctx.inf_a_id}", headers=ctx.h_a_admin)
    assert r.status_code == 204
    r2 = client.get(f"/api/v1/influencers/{ctx.inf_a_id}", headers=ctx.h_a_admin)
    assert r2.status_code == 404


def test_influencer_filter_by_status(client, ctx):
    client.post("/api/v1/influencers", headers=ctx.h_a_admin,
                json={"display_name": "Pausada", "status": "paused"})
    r = client.get("/api/v1/influencers?status=paused", headers=ctx.h_a_admin)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert all(i["status"] == "paused" for i in data)
    assert any(i["display_name"] == "Pausada" for i in data)


def test_influencer_filter_invalid_status_422(client, ctx):
    r = client.get("/api/v1/influencers?status=zzz", headers=ctx.h_a_admin)
    assert r.status_code == 422


def test_influencer_filter_by_platform(client, ctx):
    r = client.get("/api/v1/influencers?platform=instagram", headers=ctx.h_a_admin)
    assert r.status_code == 200
    names = [i["display_name"] for i in r.get_json()["data"]]
    assert "Influ A" in names  # tem conta instagram


def test_influencer_search(client, ctx):
    r = client.get("/api/v1/influencers?search=Influ%20A", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert len(r.get_json()["data"]) == 1


def test_influencer_out_has_aggregates(client, ctx):
    r = client.get(f"/api/v1/influencers/{ctx.inf_a_id}", headers=ctx.h_a_admin)
    data = r.get_json()["data"]
    assert data["total_followers"] == 1000
    assert data["platforms"] == ["instagram"]


# --------------------------------------------------------------------------
# Social Accounts
# --------------------------------------------------------------------------
def test_social_account_never_exposes_tokens(client, ctx):
    r = client.get(f"/api/v1/social-accounts/{ctx.sa_a_id}", headers=ctx.h_a_admin)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "access_token_encrypted" not in data
    assert "refresh_token_encrypted" not in data
    assert data["follower_count"] == 1000


def test_social_account_filter_by_influencer(client, ctx):
    r = client.get(
        f"/api/v1/social-accounts?influencer_id={ctx.inf_a_id}", headers=ctx.h_a_admin
    )
    assert r.status_code == 200
    assert all(s["influencer_id"] == ctx.inf_a_id for s in r.get_json()["data"])


def test_create_social_account_for_other_agency_influencer_404(client, ctx):
    r = client.post(
        "/api/v1/social-accounts",
        headers=ctx.h_a_admin,
        json={"influencer_id": ctx.inf_b_id, "platform": "tiktok", "handle": "x"},
    )
    assert r.status_code == 404  # influencer não é da agência A


def test_create_social_account_ok(client, ctx):
    r = client.post(
        "/api/v1/social-accounts",
        headers=ctx.h_a_admin,
        json={"influencer_id": ctx.inf_a_id, "platform": "tiktok", "handle": "influa_tt", "follower_count": 500},
    )
    assert r.status_code == 201
    assert r.get_json()["data"]["platform"] == "tiktok"


def test_create_social_account_duplicate_409(client, ctx):
    r = client.post(
        "/api/v1/social-accounts",
        headers=ctx.h_a_admin,
        json={"influencer_id": ctx.inf_a_id, "platform": "instagram", "handle": "influa"},
    )
    assert r.status_code == 409


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------
def test_list_campaigns_scoped(client, ctx):
    r = client.get("/api/v1/campaigns", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert len(r.get_json()["data"]) == 1
    # Agência B não vê campanha de A
    r2 = client.get("/api/v1/campaigns", headers=ctx.h_b_admin)
    assert len(r2.get_json()["data"]) == 0


def test_create_campaign(client, ctx):
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Nova Marca",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "budget_brl_cents": 100000,
            "status": "draft",
        },
    )
    assert r.status_code == 201
    assert r.get_json()["data"]["brand_name"] == "Nova Marca"


def test_create_campaign_invalid_period_422(client, ctx):
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={"brand_name": "X", "period_start": "2026-04-01", "period_end": "2026-03-01"},
    )
    assert r.status_code == 422


def test_create_campaign_com_participantes(client, ctx):
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Com Elenco",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "budget_brl_cents": 100000,
            "participants": [
                {
                    "influencer_id": ctx.inf_a_id,
                    "fee_brl_cents": 50000,
                    "deliverables": "3 reels",
                }
            ],
        },
    )
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert [p["influencer_id"] for p in data["participants"]] == [ctx.inf_a_id]

    bench = client.get(
        f"/api/v1/campaigns/{data['id']}/benchmarking", headers=ctx.h_a_admin
    ).get_json()["data"]["influencers"]
    assert bench[0]["cost_brl_cents"] == 50000
    assert bench[0]["deliverables"] == "3 reels"


def test_create_campaign_sem_participantes_continua_valido(client, ctx):
    """O campo é opcional — o contrato anterior não pode ter quebrado."""
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Sem Elenco",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
        },
    )
    assert r.status_code == 201
    assert r.get_json()["data"]["participants"] == []


def test_create_campaign_com_influencer_de_outra_agencia_404(client, ctx):
    """BOLA: vincular criador de outro cliente é o pior caso desta rota."""
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Invasora",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "participants": [{"influencer_id": ctx.inf_b_id}],
        },
    )
    assert r.status_code == 404
    # Não revela que o id existe em outra agência.
    assert ctx.inf_b_id not in r.get_json()["error"]["message"]


def test_participante_invalido_nao_deixa_campanha_orfa(client, ctx):
    """A campanha é gravada com flush antes do vínculo — precisa reverter."""
    antes = len(client.get("/api/v1/campaigns", headers=ctx.h_a_admin).get_json()["data"])

    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Nao Deve Existir",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "participants": [{"influencer_id": str(uuid.uuid4())}],
        },
    )
    assert r.status_code == 404

    depois = client.get("/api/v1/campaigns", headers=ctx.h_a_admin).get_json()["data"]
    assert len(depois) == antes
    assert not any(c["brand_name"] == "Nao Deve Existir" for c in depois)


def test_create_campaign_participante_repetido_422(client, ctx):
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_admin,
        json={
            "brand_name": "Duplicada",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "participants": [
                {"influencer_id": ctx.inf_a_id},
                {"influencer_id": ctx.inf_a_id},
            ],
        },
    )
    assert r.status_code == 422


def test_viewer_nao_cria_campanha_com_participantes(client, ctx):
    r = client.post(
        "/api/v1/campaigns",
        headers=ctx.h_a_viewer,
        json={
            "brand_name": "Do Viewer",
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
            "participants": [{"influencer_id": ctx.inf_a_id}],
        },
    )
    assert r.status_code == 403


def test_campaign_filter_by_status(client, ctx):
    r = client.get("/api/v1/campaigns?status=active", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert all(c["status"] == "active" for c in r.get_json()["data"])


# --------------------------------------------------------------------------
# Agencies
# --------------------------------------------------------------------------
def test_agency_list_returns_only_own(client, ctx):
    r = client.get("/api/v1/agencies", headers=ctx.h_a_admin)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == ctx.agency_a_id


def test_get_other_agency_404(client, ctx):
    r = client.get(f"/api/v1/agencies/{ctx.agency_b_id}", headers=ctx.h_a_admin)
    assert r.status_code == 404


def test_agency_patch_admin_ok(client, ctx):
    r = client.patch(
        f"/api/v1/agencies/{ctx.agency_a_id}", headers=ctx.h_a_admin, json={"name": "Renomeada"}
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["name"] == "Renomeada"


def test_agency_usage_conta_uso_e_traz_limite_do_plano(client, ctx):
    r = client.get(f"/api/v1/agencies/{ctx.agency_a_id}/usage", headers=ctx.h_a_admin)
    assert r.status_code == 200
    data = r.get_json()["data"]

    assert set(data) == {"influencers", "analyses", "reports"}
    # A fixture cria 1 influencer na agência A; o da agência B não conta.
    assert data["influencers"]["used"] == 1
    assert data["influencers"]["limit"] == 50
    assert data["analyses"]["limit"] == 500
    assert data["analyses"]["period"] == "current_month"
    # Relatório não tem teto no plano — nulo é "sem limite", não "limite zero".
    assert data["reports"]["limit"] is None


def test_agency_usage_de_outra_agencia_404(client, ctx):
    r = client.get(f"/api/v1/agencies/{ctx.agency_b_id}/usage", headers=ctx.h_a_admin)
    assert r.status_code == 404


def test_agency_usage_sem_plano_devolve_limite_nulo(client, ctx):
    """Agência B não tem plano: a tela precisa distinguir isso de teto zero."""
    r = client.get(f"/api/v1/agencies/{ctx.agency_b_id}/usage", headers=ctx.h_b_admin)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["influencers"]["limit"] is None
    assert data["influencers"]["used"] == 1


def test_agency_patch_member_forbidden(client, ctx):
    r = client.patch(
        f"/api/v1/agencies/{ctx.agency_a_id}", headers=ctx.h_a_member, json={"name": "X"}
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
def test_list_users_scoped(client, ctx):
    r = client.get("/api/v1/users", headers=ctx.h_a_admin)
    assert r.status_code == 200
    emails = [u["email"] for u in r.get_json()["data"]]
    assert "admin@a.com" in emails
    assert "admin@b.com" not in emails


def test_create_user_admin_ok(client, ctx):
    r = client.post(
        "/api/v1/users",
        headers=ctx.h_a_admin,
        json={"email": "novo@a.com", "name": "Novo", "role": "member"},
    )
    assert r.status_code == 201
    assert r.get_json()["data"]["email"] == "novo@a.com"


def test_create_user_member_forbidden(client, ctx):
    r = client.post(
        "/api/v1/users", headers=ctx.h_a_member, json={"email": "x@a.com", "name": "X"}
    )
    assert r.status_code == 403


def test_create_user_duplicate_email_409(client, ctx):
    r = client.post(
        "/api/v1/users",
        headers=ctx.h_a_admin,
        json={"email": "member@a.com", "name": "Dup"},
    )
    assert r.status_code == 409


def test_admin_cannot_delete_self(client, ctx):
    # Descobre o id do admin A
    me = client.get("/api/v1/auth/me", headers=ctx.h_a_admin).get_json()["data"]["user"]["id"]
    r = client.delete(f"/api/v1/users/{me}", headers=ctx.h_a_admin)
    assert r.status_code == 422


def test_member_can_update_self(client, ctx):
    me = client.get("/api/v1/auth/me", headers=ctx.h_a_member).get_json()["data"]["user"]["id"]
    r = client.patch(f"/api/v1/users/{me}", headers=ctx.h_a_member, json={"name": "Renomeado"})
    assert r.status_code == 200
    assert r.get_json()["data"]["name"] == "Renomeado"


def test_ultimo_admin_nao_pode_se_rebaixar(client, ctx):
    """Rebaixar o último admin deixaria a agência sem quem a administre.

    É o mesmo buraco que `preview_own_deletion` já considera, e não tem volta
    pela interface: a ação que consertaria exige justamente ser admin. A tela
    de equipe passou a oferecer a troca de papel, então a guarda precisa estar
    no back-end, não só no formulário.
    """
    me = client.get("/api/v1/auth/me", headers=ctx.h_a_admin).get_json()["data"]["user"]["id"]
    r = client.patch(f"/api/v1/users/{me}", headers=ctx.h_a_admin, json={"role": "viewer"})
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "last_admin_role_change"

    # E continua admin de verdade, não só na resposta.
    atual = client.get("/api/v1/auth/me", headers=ctx.h_a_admin).get_json()["data"]["user"]
    assert atual["role"] == "admin"


def test_admin_pode_se_rebaixar_havendo_outro(client, ctx):
    """A guarda é sobre restar administrador, não sobre proibir a troca."""
    me = client.get("/api/v1/auth/me", headers=ctx.h_a_admin).get_json()["data"]["user"]["id"]
    segundo = client.post(
        "/api/v1/users",
        headers=ctx.h_a_admin,
        json={"email": "segundo-admin@a.com", "name": "Segundo", "role": "admin"},
    )
    assert segundo.status_code == 201

    r = client.patch(f"/api/v1/users/{me}", headers=ctx.h_a_admin, json={"role": "viewer"})
    assert r.status_code == 200
    assert r.get_json()["data"]["role"] == "viewer"


def test_member_cannot_change_own_role(client, ctx):
    me = client.get("/api/v1/auth/me", headers=ctx.h_a_member).get_json()["data"]["user"]["id"]
    r = client.patch(f"/api/v1/users/{me}", headers=ctx.h_a_member, json={"role": "admin"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Filtros de listagem — o que a tela oferece e a suíte não exercitava
# --------------------------------------------------------------------------
def _cria_influ_com_seguidores(client, ctx, nome, seguidores, plataforma="tiktok"):
    """Cria influenciador e uma conta social com a contagem pedida."""
    inf = client.post(
        "/api/v1/influencers", headers=ctx.h_a_admin,
        json={"display_name": nome, "niche": "beauty"},
    ).get_json()["data"]
    client.post(
        "/api/v1/social-accounts", headers=ctx.h_a_admin,
        json={"influencer_id": inf["id"], "platform": plataforma,
              "handle": nome.lower(), "follower_count": seguidores},
    )
    return inf["id"]


def _nomes(resposta):
    return {i["display_name"] for i in resposta.get_json()["data"]}


def test_filtro_de_seguidores_respeita_o_minimo(client, ctx):
    _cria_influ_com_seguidores(client, ctx, "Micro", 5_000)
    _cria_influ_com_seguidores(client, ctx, "Macro", 800_000)

    r = client.get("/api/v1/influencers?follower_min=100000", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert _nomes(r) == {"Macro"}


def test_filtro_de_seguidores_respeita_o_maximo(client, ctx):
    _cria_influ_com_seguidores(client, ctx, "Micro", 5_000)
    _cria_influ_com_seguidores(client, ctx, "Macro", 800_000)

    r = client.get("/api/v1/influencers?follower_max=100000", headers=ctx.h_a_admin)
    assert "Macro" not in _nomes(r)
    assert "Micro" in _nomes(r)


def test_faixa_de_seguidores_soma_as_contas_do_criador(client, ctx):
    # A tela oferece faixas ("100k – 500k") e o criador costuma ter mais de uma
    # plataforma: filtrar por conta isolada colocaria na faixa errada quem tem
    # 60k no Instagram e 60k no TikTok.
    inf = client.post(
        "/api/v1/influencers", headers=ctx.h_a_admin,
        json={"display_name": "Somado", "niche": "fitness"},
    ).get_json()["data"]
    for plataforma in ("instagram", "tiktok"):
        client.post(
            "/api/v1/social-accounts", headers=ctx.h_a_admin,
            json={"influencer_id": inf["id"], "platform": plataforma,
                  "handle": f"somado_{plataforma}", "follower_count": 60_000},
        )

    acima = client.get("/api/v1/influencers?follower_min=100000", headers=ctx.h_a_admin)
    assert "Somado" in _nomes(acima)


def test_faixa_de_seguidores_combina_minimo_e_maximo(client, ctx):
    _cria_influ_com_seguidores(client, ctx, "Micro", 5_000)
    _cria_influ_com_seguidores(client, ctx, "Mid", 250_000)
    _cria_influ_com_seguidores(client, ctx, "Macro", 800_000)

    r = client.get(
        "/api/v1/influencers?follower_min=100000&follower_max=500000", headers=ctx.h_a_admin
    )
    assert _nomes(r) == {"Mid"}


def test_criador_sem_conta_social_nao_soma_seguidor_nenhum(client, ctx):
    # Criador recém-cadastrado, ainda sem conta conectada, tem zero seguidor —
    # e zero está dentro de "menos de 100k". Sumir da faixa esconde justamente
    # quem acabou de entrar e precisa ser conectado.
    client.post(
        "/api/v1/influencers", headers=ctx.h_a_admin,
        json={"display_name": "Recem Cadastrado", "niche": "games"},
    )
    r = client.get("/api/v1/influencers?follower_max=100000", headers=ctx.h_a_admin)
    assert "Recem Cadastrado" in _nomes(r)


def test_campanha_filtra_por_inicio_e_fim_do_periodo(client, ctx):
    client.post(
        "/api/v1/campaigns", headers=ctx.h_a_admin,
        json={"brand_name": "Marca Nova", "period_start": "2026-06-01",
              "period_end": "2026-07-01"},
    )
    depois = client.get("/api/v1/campaigns?starts_after=2026-05-01", headers=ctx.h_a_admin)
    assert {c["brand_name"] for c in depois.get_json()["data"]} == {"Marca Nova"}

    antes = client.get("/api/v1/campaigns?ends_before=2026-03-01", headers=ctx.h_a_admin)
    assert {c["brand_name"] for c in antes.get_json()["data"]} == {"Marca A"}


def test_campanha_busca_por_marca_ignora_caixa(client, ctx):
    r = client.get("/api/v1/campaigns?search=marca a", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert {c["brand_name"] for c in r.get_json()["data"]} == {"Marca A"}


def test_campanha_busca_sem_correspondencia_devolve_lista_vazia(client, ctx):
    r = client.get("/api/v1/campaigns?search=inexistente", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert r.get_json()["data"] == []


def test_patch_de_campanha_recusa_periodo_invertido_no_merge(client, ctx):
    # A validação tem que olhar o período *resultante*: mandar só o fim, com o
    # início vindo do que já está gravado, é o caminho que passa despercebido.
    r = client.patch(
        f"/api/v1/campaigns/{ctx.camp_a_id}", headers=ctx.h_a_admin,
        json={"period_end": "2025-12-01"},
    )
    assert r.status_code == 422


def test_patch_de_campanha_aceita_periodo_coerente(client, ctx):
    r = client.patch(
        f"/api/v1/campaigns/{ctx.camp_a_id}", headers=ctx.h_a_admin,
        json={"period_end": "2026-03-01", "brand_name": "Marca A Renomeada"},
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["brand_name"] == "Marca A Renomeada"


def test_delete_de_campanha_remove_da_listagem(client, ctx):
    assert client.delete(f"/api/v1/campaigns/{ctx.camp_a_id}",
                         headers=ctx.h_a_admin).status_code in (200, 204)
    r = client.get("/api/v1/campaigns", headers=ctx.h_a_admin)
    assert ctx.camp_a_id not in {c["id"] for c in r.get_json()["data"]}


def test_conta_social_com_id_de_criador_malformado_devolve_lista_vazia(client, ctx):
    # Id quebrado vem de link velho ou digitação, não é ataque: a listagem
    # filtra para conjunto vazio em vez de estourar 500.
    r = client.get("/api/v1/social-accounts?influencer_id=nao-e-uuid", headers=ctx.h_a_admin)
    assert r.status_code == 200
    assert r.get_json()["data"] == []


def test_plano_com_id_malformado_devolve_404(client, ctx):
    r = client.get("/api/v1/plans/nao-e-uuid", headers=ctx.h_a_admin)
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Participantes de uma campanha já existente
# --------------------------------------------------------------------------
# Até esta frente os participantes só podiam ser escolhidos na criação: depois
# disso a lista era imutável, num produto cuja unidade de trabalho é a campanha.
def test_vincular_criador_a_campanha_existente(client, ctx):
    r = client.post(
        f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
        headers=ctx.h_a_admin,
        json={"influencer_id": ctx.inf_a_id, "fee_brl_cents": 250000},
    )
    assert r.status_code == 201
    corpo = r.get_json()["data"]
    assert corpo["influencer_id"] == ctx.inf_a_id
    assert corpo["fee_brl_cents"] == 250000

    detalhe = client.get(f"/api/v1/campaigns/{ctx.camp_a_id}", headers=ctx.h_a_admin)
    ids = [p["influencer_id"] for p in detalhe.get_json()["data"]["participants"]]
    assert ctx.inf_a_id in ids


def test_vincular_duas_vezes_e_conflito_e_nao_erro_de_banco(client, ctx):
    client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                headers=ctx.h_a_admin, json={"influencer_id": ctx.inf_a_id})
    r = client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                    headers=ctx.h_a_admin, json={"influencer_id": ctx.inf_a_id})
    # A chave única já barraria, mas com 500. Conflito explícito é o que
    # permite a interface dizer o que houve.
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "participant_already_linked"


def test_criador_de_outra_agencia_nao_entra_na_campanha(client, ctx):
    # Mesmo 404 de id inexistente: responder diferente revelaria quais ids
    # existem na outra agência.
    r = client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                    headers=ctx.h_a_admin, json={"influencer_id": ctx.inf_b_id})
    assert r.status_code == 404


def test_desvincular_preserva_o_criador_e_os_posts(client, ctx):
    client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                headers=ctx.h_a_admin, json={"influencer_id": ctx.inf_a_id})
    r = client.delete(
        f"/api/v1/campaigns/{ctx.camp_a_id}/participants/{ctx.inf_a_id}",
        headers=ctx.h_a_admin,
    )
    assert r.status_code == 204

    # Sair de uma campanha não é deixar de existir.
    assert client.get(f"/api/v1/influencers/{ctx.inf_a_id}",
                      headers=ctx.h_a_admin).status_code == 200
    detalhe = client.get(f"/api/v1/campaigns/{ctx.camp_a_id}", headers=ctx.h_a_admin)
    assert detalhe.get_json()["data"]["participants"] == []


def test_desvincular_quem_nao_esta_na_campanha_e_404(client, ctx):
    r = client.delete(
        f"/api/v1/campaigns/{ctx.camp_a_id}/participants/{ctx.inf_a_id}",
        headers=ctx.h_a_admin,
    )
    assert r.status_code == 404


def test_id_malformado_de_criador_nao_estoura_500(client, ctx):
    r = client.delete(
        f"/api/v1/campaigns/{ctx.camp_a_id}/participants/nao-e-uuid",
        headers=ctx.h_a_admin,
    )
    assert r.status_code == 404


def test_viewer_nao_mexe_nos_participantes(client, ctx):
    r = client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                    headers=ctx.h_a_viewer, json={"influencer_id": ctx.inf_a_id})
    assert r.status_code == 403


def test_campanha_de_outra_agencia_nao_aceita_participante(client, ctx):
    r = client.post(f"/api/v1/campaigns/{ctx.camp_a_id}/participants",
                    headers=ctx.h_b_admin, json={"influencer_id": ctx.inf_b_id})
    assert r.status_code == 404
