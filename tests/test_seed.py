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


# --------------------------------------------------------------------------
# seed refresh (25/11/2026)
# --------------------------------------------------------------------------
def _envelhecer_posts(dias: int) -> None:
    """Simula o seed rodado `dias` atrás: empurra posts, comentários e análises."""
    from datetime import timedelta

    from src.models import AIAnalysis, Comment

    # Linha a linha, e não num UPDATE: o SQLite da suíte não subtrai intervalo.
    for modelo, coluna in ((Post, "posted_at"), (Comment, "posted_at"), (AIAnalysis, "analyzed_at")):
        for linha in db.session.scalars(select(modelo)):
            setattr(linha, coluna, getattr(linha, coluna) - timedelta(days=dias))
    db.session.commit()


def test_seed_refresh_traz_o_painel_de_30_dias_de_volta(app, fresh_db):
    from src.seed.seed_data import seed_refresh
    from src.services import dashboard_service

    with app.app_context():
        seed_run()
        _envelhecer_posts(120)
        agency = db.session.scalar(select(Agency).where(Agency.name == SEEDED_AGENCY_NAME))
        antes = dashboard_service.overview(agency.id, period="30d")

        stats = seed_refresh()
        depois = dashboard_service.overview(agency.id, period="30d")
        assert depois["growth_trajectory"] != antes["growth_trajectory"]
        assert depois["top_performing"], "o painel de 30 dias deveria ter posts"
        assert 100 <= stats["posts"] <= 300
        assert stats["comments"] >= stats["posts"] * 12
        assert stats["ai_analyses"] > 0

        recentes = db.session.scalar(
            select(func.count(Post.id)).where(Post.platform_post_id.contains("-r"))
        )
        assert recentes == stats["posts"]


def test_seed_refresh_nao_toca_conta_conectada(app, fresh_db):
    from src.models import SocialAccount
    from src.seed.seed_data import seed_refresh

    with app.app_context():
        seed_run()
        _envelhecer_posts(60)
        conta = db.session.scalar(select(SocialAccount).order_by(SocialAccount.id))
        conta.platform_user_id = "real-123"  # o callback de conexão grava o id da rede
        db.session.commit()
        antes = db.session.scalar(select(func.count(Post.id)).where(Post.social_account_id == conta.id))

        seed_refresh()

        depois = db.session.scalar(select(func.count(Post.id)).where(Post.social_account_id == conta.id))
        assert depois == antes


def test_seed_refresh_seguido_nao_acrescenta_nada_e_dry_run_nao_grava(app, fresh_db):
    from src.seed.seed_data import seed_refresh

    with app.app_context():
        seed_run()
        _envelhecer_posts(45)
        total = db.session.scalar(select(func.count(Post.id)))

        simulado = seed_refresh(gravar=False)
        assert simulado["posts"] > 0
        assert db.session.scalar(select(func.count(Post.id))) == total

        seed_refresh()
        assert seed_refresh()["posts"] == 0


def test_seed_refresh_sem_seed_avisa(app, fresh_db):
    from src.seed.seed_data import seed_refresh

    with app.app_context():
        with pytest.raises(RuntimeError, match="seed run"):
            seed_refresh()
