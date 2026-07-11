"""Testes de modelagem — relacionamentos, constraints e soft delete."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from src.models import (
    Agency,
    Campaign,
    CampaignInfluencer,
    CampaignStatus,
    Influencer,
    InfluencerStatus,
    OAuthProvider,
    Plan,
    Platform,
    SocialAccount,
    User,
    UserRole,
)


@pytest.fixture()
def plan(db_session):
    p = Plan(name="Agency", max_influencers=50, max_analyses_per_month=200, price_brl_cents=129700)
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture()
def agency(db_session, plan):
    a = Agency(name="Agência Teste", cnpj="00.000.000/0001-00", plan=plan)
    db_session.add(a)
    db_session.flush()
    return a


def test_agency_belongs_to_plan(db_session, agency, plan):
    assert agency.plan_id == plan.id
    assert agency in plan.agencies


def test_user_linked_to_agency(db_session, agency):
    user = User(
        email="gustavo@teste.com",
        name="Gustavo",
        oauth_provider=OAuthProvider.GOOGLE,
        oauth_id="google-123",
        role=UserRole.ADMIN,
        agency=agency,
    )
    db_session.add(user)
    db_session.flush()

    # Relação bidirecional
    assert user.agency is agency
    assert user in agency.users


def test_influencer_with_two_social_accounts(db_session, agency):
    inf = Influencer(
        agency=agency,
        display_name="Nina Silva",
        niche="tech",
        status=InfluencerStatus.ACTIVE,
    )
    db_session.add(inf)
    db_session.flush()

    ig = SocialAccount(
        influencer=inf, platform=Platform.INSTAGRAM, handle="ninasilva", follower_count=120_000
    )
    tt = SocialAccount(
        influencer=inf, platform=Platform.TIKTOK, handle="nina.silva", follower_count=80_000
    )
    db_session.add_all([ig, tt])
    db_session.flush()

    fetched = db_session.scalar(select(Influencer).where(Influencer.id == inf.id))
    assert len(fetched.social_accounts) == 2
    platforms = {sa.platform for sa in fetched.social_accounts}
    assert platforms == {Platform.INSTAGRAM, Platform.TIKTOK}

    # Bidirecional
    assert ig.influencer is inf
    assert tt.influencer is inf

    # Bidirecional ao nível da agência
    assert inf in agency.influencers


def test_campaign_with_influencer_via_association(db_session, agency):
    inf = Influencer(agency=agency, display_name="Carla Tech")
    db_session.add(inf)
    db_session.flush()

    camp = Campaign(
        agency=agency,
        brand_name="MarcaX",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        budget_brl_cents=500_000,
        status=CampaignStatus.ACTIVE,
    )
    db_session.add(camp)
    db_session.flush()

    link = CampaignInfluencer(campaign=camp, influencer=inf, fee_brl_cents=300_000)
    db_session.add(link)
    db_session.flush()

    assert len(camp.influencer_links) == 1
    assert camp.influencer_links[0].influencer is inf
    assert inf.campaign_links[0].campaign is camp


def test_soft_delete_on_agency(db_session, agency):
    assert agency.deleted_at is None
    assert agency.is_deleted is False

    agency.deleted_at = datetime.now(timezone.utc)
    db_session.flush()

    refreshed = db_session.scalar(select(Agency).where(Agency.id == agency.id))
    assert refreshed.deleted_at is not None
    assert refreshed.is_deleted is True


def test_user_unique_email(db_session, agency):
    u1 = User(
        email="dup@teste.com",
        name="Primeiro",
        oauth_provider=OAuthProvider.GOOGLE,
        oauth_id="g-1",
        agency=agency,
    )
    db_session.add(u1)
    db_session.flush()

    u2 = User(
        email="dup@teste.com",
        name="Segundo",
        oauth_provider=OAuthProvider.MICROSOFT,
        oauth_id="ms-2",
        agency=agency,
    )
    db_session.add(u2)
    with pytest.raises(Exception):  # IntegrityError no SQLite/PG
        db_session.flush()
    db_session.rollback()


def test_social_account_unique_per_influencer_platform_handle(db_session, agency):
    inf = Influencer(agency=agency, display_name="Dup Test")
    db_session.add(inf)
    db_session.flush()

    sa1 = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="same")
    db_session.add(sa1)
    db_session.flush()

    sa2 = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="same")
    db_session.add(sa2)
    with pytest.raises(Exception):
        db_session.flush()
    db_session.rollback()
