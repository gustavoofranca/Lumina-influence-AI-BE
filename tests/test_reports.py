"""Testes da B10 — geração, listagem e download de relatórios PDF."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import (
    Agency,
    Campaign,
    CampaignInfluencer,
    CampaignStatus,
    Comment,
    Influencer,
    OAuthProvider,
    Platform,
    Post,
    PostType,
    Report,
    SocialAccount,
    User,
    UserRole,
)
from src.services import report_service
from src.utils.jwt_utils import issue_token_pair


class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for m in (Report, Comment, Post, CampaignInfluencer, Campaign, SocialAccount,
                  Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()

        agency = Agency(name="Ag")
        other = Agency(name="Other")
        db.session.add_all([agency, other])
        db.session.flush()
        admin = User(email="a@a.com", name="Admin A", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        viewer = User(email="v@a.com", name="V", oauth_provider=OAuthProvider.GOOGLE,
                      oauth_id="ov", role=UserRole.VIEWER, agency=agency)
        db.session.add_all([admin, viewer])

        inf = Influencer(agency=agency, display_name="Nina Tech", niche="tech")
        db.session.add(inf)
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="nina", follower_count=100000)
        db.session.add(sa)
        db.session.flush()

        camp = Campaign(agency=agency, brand_name="NovaTech", title="Verão Tech",
                        period_start=date(2026, 1, 1), period_end=date(2026, 3, 1),
                        budget_brl_cents=5000000, status=CampaignStatus.ACTIVE)
        camp_other = Campaign(agency=other, brand_name="X", period_start=date(2026, 1, 1),
                              period_end=date(2026, 2, 1), status=CampaignStatus.ACTIVE)
        db.session.add_all([camp, camp_other])
        db.session.flush()
        db.session.add(CampaignInfluencer(campaign=camp, influencer=inf, fee_brl_cents=100000))

        # alguns posts da campanha (pra ter dados no relatório)
        for i in range(3):
            db.session.add(Post(
                social_account=sa, campaign=camp, platform_post_id=f"p{i}",
                post_type=PostType.REEL, posted_at=datetime.now(timezone.utc),
                reach_total=10000, reach_organic=7000, reach_paid=3000, impressions=15000,
                likes=800, comments_count=40, shares=20, saves=30,
            ))
        db.session.commit()

        c = Ctx()
        c.agency_id = agency.id
        c.camp_id = str(camp.id)
        c.camp_other_id = str(camp_other.id)
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.h_viewer = {"Authorization": f"Bearer {issue_token_pair(viewer)['access_token']}"}
        yield c

        # limpa PDFs gerados
        with app.app_context():
            for r in db.session.scalars(select(Report)).all():
                p = report_service.report_pdf_path(r)
                if p.exists():
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            for m in (Report, Comment, Post, CampaignInfluencer, Campaign, SocialAccount,
                      Influencer, User, Agency):
                db.session.query(m).delete()
            db.session.commit()


def _create_payload(camp_id, sections=None):
    return {
        "campaign_id": camp_id,
        "title": "Relatório Verão Tech",
        "period_start": "2026-01-01",
        "period_end": "2026-03-01",
        "sections": sections if sections is not None else ["kpis", "benchmark", "recommendations"],
    }


# ==========================================================================
# POST /reports — gera PDF real
# ==========================================================================
def test_create_report_generates_pdf(client, ctx, app):
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=_create_payload(ctx.camp_id))
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert data["title"] == "Relatório Verão Tech"
    assert data["pdf_url"].endswith("/download")
    assert data["format"] == "pdf"

    with app.app_context():
        report = db.session.get(Report, uuid.UUID(data["id"]))
        path = report_service.report_pdf_path(report)
        assert path.exists()
        assert path.read_bytes()[:5] == b"%PDF-"


def test_create_report_invalid_section_422(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_admin,
                    json=_create_payload(ctx.camp_id, sections=["kpis", "inexistente"]))
    assert r.status_code == 422


def test_create_report_other_agency_campaign_404(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_admin,
                    json=_create_payload(ctx.camp_other_id))
    assert r.status_code == 404


def test_create_report_viewer_forbidden(client, ctx):
    r = client.post("/api/v1/reports", headers=ctx.h_viewer, json=_create_payload(ctx.camp_id))
    assert r.status_code == 403


def test_create_report_invalid_period_422(client, ctx):
    payload = _create_payload(ctx.camp_id)
    payload["period_start"], payload["period_end"] = "2026-03-01", "2026-01-01"
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=payload)
    assert r.status_code == 422


# ==========================================================================
# GET /reports — listagem escopada
# ==========================================================================
def test_list_reports_scoped(client, ctx):
    client.post("/api/v1/reports", headers=ctx.h_admin, json=_create_payload(ctx.camp_id))
    r = client.get("/api/v1/reports", headers=ctx.h_admin)
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) == 1
    assert "pagination" in body["meta"]


# ==========================================================================
# GET /reports/:id/download — baixa o PDF
# ==========================================================================
def test_download_report_returns_pdf(client, ctx):
    created = client.post("/api/v1/reports", headers=ctx.h_admin,
                          json=_create_payload(ctx.camp_id)).get_json()["data"]
    r = client.get(f"/api/v1/reports/{created['id']}/download", headers=ctx.h_admin)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"


def test_download_other_agency_404(client, ctx):
    r = client.get(f"/api/v1/reports/{uuid.uuid4()}/download", headers=ctx.h_admin)
    assert r.status_code == 404


def test_full_sections_report(client, ctx, app):
    """Relatório com todas as seções gera PDF maior sem erro."""
    payload = _create_payload(ctx.camp_id,
                              sections=["kpis", "growth", "benchmark", "diagnostic", "recommendations"])
    r = client.post("/api/v1/reports", headers=ctx.h_admin, json=payload)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["sections"]["included"] == ["kpis", "growth", "benchmark", "diagnostic", "recommendations"]
    with app.app_context():
        report = db.session.get(Report, uuid.UUID(data["id"]))
        assert report_service.report_pdf_path(report).read_bytes()[:5] == b"%PDF-"
