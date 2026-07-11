"""Smoke test do seed — valida que seed_run popula o esperado e seed_clear limpa."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Agency,
    Influencer,
    Post,
)
from src.seed.seed_data import SEEDED_AGENCY_NAME, seed_clear, seed_run


@pytest.fixture()
def fresh_db(app):
    """Limpa o banco antes do teste e depois também."""
    with app.app_context():
        seed_clear()
        yield
        seed_clear()


def test_seed_run_populates_expected_counts(app, fresh_db):
    with app.app_context():
        stats = seed_run()

    # Volumes alvo (B2 spec)
    assert stats["plans"] >= 1
    assert stats["agencies"] == 1
    assert stats["users"] == 6
    assert stats["influencers"] == 15
    assert 25 <= stats["social_accounts"] <= 35
    assert stats["campaigns"] == 5
    assert 150 <= stats["posts"] <= 250, f"posts={stats['posts']} fora do range esperado"
    assert 2000 <= stats["comments"] <= 4000, f"comments={stats['comments']}"
    assert 100 <= stats["ai_analyses"] <= 200, f"ai_analyses={stats['ai_analyses']}"
    assert stats["reports"] >= 3


def test_seed_run_creates_canonical_agency_with_relationships(app, fresh_db):
    with app.app_context():
        seed_run()
        agency = db.session.scalar(select(Agency).where(Agency.name == SEEDED_AGENCY_NAME))
        assert agency is not None
        assert agency.plan is not None
        assert agency.plan.name == "Agency"
        assert len(agency.users) == 6
        assert len(agency.influencers) == 15
        # Pelo menos 1 admin
        assert any(u.role.value == "admin" for u in agency.users)


def test_seed_run_is_idempotent_via_clear(app, fresh_db):
    with app.app_context():
        seed_run()
        deleted = seed_clear()
        assert deleted["agencies"] == 1
        assert db.session.scalar(select(func.count(Agency.id))) == 0
        # Re-seed funciona após clear
        stats = seed_run()
        assert stats["influencers"] == 15


def test_seed_run_refuses_to_double_seed(app, fresh_db):
    with app.app_context():
        seed_run()
        with pytest.raises(RuntimeError, match="já existe"):
            seed_run()


def test_seeded_influencer_has_at_least_one_social_account(app, fresh_db):
    with app.app_context():
        seed_run()
        influencers = db.session.scalars(select(Influencer)).all()
        for inf in influencers:
            assert len(inf.social_accounts) >= 1, (
                f"influencer {inf.display_name} sem conta social"
            )


def test_seeded_post_has_consistent_reach_split(app, fresh_db):
    with app.app_context():
        seed_run()
        posts = db.session.scalars(select(Post).limit(50)).all()
        for p in posts:
            # reach_total = organic + paid (com tolerância de arredondamento)
            assert abs(p.reach_total - (p.reach_organic + p.reach_paid)) <= 1
            assert p.likes <= p.reach_total
