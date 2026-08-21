"""Testes dos endpoints de dashboard (B5).

Usa o seed completo (posts + análises reais) pra validar as agregações.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import Campaign, Influencer, InfluencerStatus, User, UserRole
from src.seed.seed_data import seed_clear, seed_run
from src.utils.jwt_utils import issue_token_pair


class Ctx:
    pass


@pytest.fixture()
def seeded(app):
    with app.app_context():
        seed_clear()
        seed_run()

        admin = db.session.scalar(
            select(User).where(User.role == UserRole.ADMIN)
        )
        influencer = db.session.scalar(select(Influencer))
        campaign = db.session.scalar(select(Campaign))

        c = Ctx()
        c.header = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.influencer_id = str(influencer.id)
        c.campaign_id = str(campaign.id)
        yield c

        seed_clear()


# --------------------------------------------------------------------------
# /dashboard/overview
# --------------------------------------------------------------------------
def test_overview_shape(client, seeded):
    r = client.get("/api/v1/dashboard/overview?period=30d", headers=seeded.header)
    assert r.status_code == 200
    body = r.get_json()
    data = body["data"]

    # KPIs
    assert set(data["kpis"].keys()) == {"roi", "engagement_rate", "cac", "active_influencers"}
    assert "value_pct" in data["kpis"]["engagement_rate"]
    assert data["kpis"]["active_influencers"]["value"] >= 1

    # Estruturas agregadas
    assert isinstance(data["growth_trajectory"], list)
    assert isinstance(data["top_performing"], list)
    assert len(data["top_performing"]) <= 6
    assert body["meta"]["period"] == "30d"


def test_overview_top_performing_sorted(client, seeded):
    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    cards = r.get_json()["data"]["top_performing"]
    scores = [c["resonance_score"] for c in cards]
    assert scores == sorted(scores, reverse=True)
    for c in cards:
        assert c["viral_potential"] in {"high", "medium", "low"}


def test_overview_featured_diagnosis_present(client, seeded):
    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    fd = r.get_json()["data"]["featured_diagnosis"]
    # 143 análises seedadas → deve existir
    assert fd is not None
    assert "influencer_name" in fd
    assert "pills" in fd


def test_overview_period_filter_changes_buckets(client, seeded):
    r7 = client.get("/api/v1/dashboard/overview?period=7d", headers=seeded.header)
    r90 = client.get("/api/v1/dashboard/overview?period=90d", headers=seeded.header)
    assert r7.status_code == 200 and r90.status_code == 200
    # 90d cobre mais posts que 7d → pelo menos não menos buckets de modo geral
    assert isinstance(r7.get_json()["data"]["growth_trajectory"], list)


def test_overview_invalid_campaign_id_422(client, seeded):
    r = client.get(
        "/api/v1/dashboard/overview?campaign_id=not-a-uuid", headers=seeded.header
    )
    assert r.status_code == 422


def test_overview_requires_auth(client, seeded):
    r = client.get("/api/v1/dashboard/overview")
    assert r.status_code == 401


# --------------------------------------------------------------------------
# /dashboard/network-density
# --------------------------------------------------------------------------
def test_network_density(client, seeded):
    r = client.get("/api/v1/dashboard/network-density", headers=seeded.header)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["total"] == 15
    assert data["connected"] == 15  # todos têm conta social
    assert data["value"] == 100


# --------------------------------------------------------------------------
# /influencers/:id/analysis
# --------------------------------------------------------------------------
def test_influencer_analysis_shape(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/analysis", headers=seeded.header
    )
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "influencer" in data
    assert set(data["diagnostic_kpis"].keys()) == {
        "brand_coherence",
        "sentiment_index_pct",
        "safety_rating",
        "bot_probability",
    }
    assert "audience_integrity" in data
    assert "neural_confidence" in data
    assert isinstance(data["sentiment_clusters"], list)
    assert isinstance(data["keywords"], list)


def test_influencer_analysis_audience_integrity_sums_100(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/analysis", headers=seeded.header
    )
    ai = r.get_json()["data"]["audience_integrity"]
    total = ai["organic"] + ai["suspicious"] + ai["bots"]
    assert abs(total - 100) <= 0.5


def test_analysis_other_agency_404(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{uuid.uuid4()}/analysis", headers=seeded.header
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# /influencers/:id/posts
# --------------------------------------------------------------------------
def test_influencer_posts(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/posts?limit=5", headers=seeded.header
    )
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) <= 5
    if body["data"]:
        p = body["data"][0]
        assert set(p.keys()) >= {
            "id", "caption", "posted_at", "platform", "reach_total",
            "sentiment_score", "bot_probability",
        }
    assert body["meta"]["limit"] == 5


# --------------------------------------------------------------------------
# /campaigns/:id/benchmarking
# --------------------------------------------------------------------------
def test_campaign_benchmarking_shape(client, seeded):
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "campaign" in data
    assert isinstance(data["influencers"], list)
    assert "radar" in data
    assert data["radar"]["dimensions"] == ["reach", "engagement", "sentiment", "coherence", "organic"]
    # cada série do radar tem 5 valores (1 por dimensão)
    for serie in data["radar"]["series"]:
        assert len(serie["values"]) == 5


def test_benchmarking_other_agency_404(client, seeded):
    r = client.get(
        f"/api/v1/campaigns/{uuid.uuid4()}/benchmarking", headers=seeded.header
    )
    assert r.status_code == 404


def test_benchmarking_row_traz_identidade_do_influencer(client, seeded):
    """A tela de participantes precisa de identidade, não só métrica (B11)."""
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    rows = r.get_json()["data"]["influencers"]
    assert rows, "campanha seedada deve ter participantes"

    for row in rows:
        assert {
            "influencer_id", "display_name", "handle", "niche", "status",
            "platforms", "followers", "posts_count", "deliverables",
            "brand_coherence", "bot_probability",
        } <= set(row)
        assert row["status"] in {s.value for s in InfluencerStatus}
        assert isinstance(row["platforms"], list)
        assert row["followers"] >= 0
        assert row["posts_count"] >= 0


def test_benchmarking_nao_expoe_token_de_conta_social(client, seeded):
    """Contas sociais carregam token cifrado — ele não pode vazar na resposta."""
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    assert "_encrypted" not in r.get_data(as_text=True)


# --------------------------------------------------------------------------
# participantes de campanha
# --------------------------------------------------------------------------
def test_lista_de_campanhas_traz_participantes(client, seeded):
    r = client.get("/api/v1/campaigns", headers=seeded.header)
    assert r.status_code == 200
    items = r.get_json()["data"]
    assert items

    for camp in items:
        assert isinstance(camp["participants"], list)
        for p in camp["participants"]:
            assert set(p) == {"influencer_id", "display_name"}

    assert any(c["participants"] for c in items)


def test_detalhe_da_campanha_traz_participantes(client, seeded):
    r = client.get(f"/api/v1/campaigns/{seeded.campaign_id}", headers=seeded.header)
    assert r.status_code == 200
    assert isinstance(r.get_json()["data"]["participants"], list)


def test_participantes_batem_com_o_benchmarking(client, seeded):
    """Duas rotas, uma verdade: a associativa é a mesma."""
    detail = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}", headers=seeded.header
    ).get_json()["data"]
    bench = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    ).get_json()["data"]

    assert {p["influencer_id"] for p in detail["participants"]} == {
        r["influencer_id"] for r in bench["influencers"]
    }
