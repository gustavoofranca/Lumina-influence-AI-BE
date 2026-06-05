"""Testes dos background jobs (B7) — lógica síncrona, sem scheduler/rede."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from src.extensions import db
from src.integrations.gemini import GeminiQuotaError, GeminiResult
from src.jobs.cleanup_expired_tokens import run_cleanup_expired_tokens
from src.jobs.run_pending_analyses import run_pending_analyses
from src.jobs.sync_metrics import run_sync_metrics
from src.models import (
    AIAnalysis,
    Agency,
    ApiUsageLog,
    Comment,
    Influencer,
    OAuthProvider,
    OAuthState,
    Platform,
    Post,
    PostType,
    SocialAccount,
)


GOOD_JSON = (
    '{"sentiment_score":0.6,"sentiment_label":"positive",'
    '"sentiment_breakdown":{"technical_enthusiasm":40,"purchase_intent":30,"value_skepticism":10,"neutral":20},'
    '"script_score":8,"brand_coherence_score":90,"bot_probability":6,'
    '"key_phrases":["bom"],"recommendations":[{"priority":"high","title":"X","description":"Y"}]}'
)


def _fake_client(text=GOOD_JSON, tokens=100):
    class _Fake:
        def __init__(self, *a, **k):
            pass

        def generate_json(self, prompt):
            return GeminiResult(text=text, total_tokens=tokens, model="gemini-test")

    return _Fake()


def _raising_client(exc):
    class _Fake:
        def __init__(self, *a, **k):
            pass

        def generate_json(self, prompt):
            raise exc

    return _Fake()


class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for model in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, OAuthState, Agency):
            db.session.query(model).delete()
        db.session.commit()

        agency = Agency(name="Ag")
        db.session.add(agency)
        db.session.flush()
        inf = Influencer(agency=agency, display_name="Inf", niche="tech")
        db.session.add(inf)
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.INSTAGRAM, handle="h")
        db.session.add(sa)
        db.session.flush()

        def mk_post(idx, posted_at, needs=False):
            p = Post(
                social_account=sa, platform_post_id=f"p{idx}", post_type=PostType.REEL,
                posted_at=posted_at, caption="cap", reach_total=10000, reach_organic=7000,
                reach_paid=3000, impressions=15000, likes=1000, comments_count=50,
                shares=30, saves=40, needs_analysis=needs,
            )
            db.session.add(p)
            return p

        now = datetime.now(timezone.utc)
        recent = mk_post(1, now, needs=False)
        old = mk_post(2, now - timedelta(days=30), needs=False)
        pending = mk_post(3, now, needs=True)
        db.session.flush()
        db.session.add(Comment(post=pending, platform_comment_id="c1", content="ótimo",
                               author_handle="u", posted_at=now))
        db.session.commit()

        c = Ctx()
        c.agency_id = agency.id
        c.recent_id = recent.id
        c.old_id = old.id
        c.pending_id = pending.id
        yield c

        for model in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, OAuthState, Agency):
            db.session.query(model).delete()
        db.session.commit()


# --------------------------------------------------------------------------
# sync_metrics
# --------------------------------------------------------------------------
def test_sync_metrics_grows_recent_only(app, ctx):
    with app.app_context():
        recent_before = db.session.get(Post, ctx.recent_id).likes
        old_before = db.session.get(Post, ctx.old_id).likes

        result = run_sync_metrics(rng=random.Random(1))
        assert result["posts_updated"] >= 2  # recent + pending (ambos de hoje)

        recent_after = db.session.get(Post, ctx.recent_id)
        old_after = db.session.get(Post, ctx.old_id)
        assert recent_after.likes >= recent_before  # cresceu
        assert recent_after.reach_total == recent_after.reach_organic + recent_after.reach_paid
        assert old_after.likes == old_before  # post antigo intocado
        assert recent_after.social_account.last_synced_at is not None


# --------------------------------------------------------------------------
# run_pending_analyses
# --------------------------------------------------------------------------
def test_pending_analyses_processes_and_unmarks(app, ctx):
    with app.app_context():
        result = run_pending_analyses(limit=5, client=_fake_client())
        assert result["analyzed"] == 1

        post = db.session.get(Post, ctx.pending_id)
        assert post.needs_analysis is False
        # análise persistida + uso logado
        assert db.session.scalar(select(func.count(AIAnalysis.id))) == 1
        assert db.session.scalar(select(func.count(ApiUsageLog.id))) == 1


def test_pending_analyses_nothing_pending(app, ctx):
    with app.app_context():
        # desmarca o único pendente
        db.session.get(Post, ctx.pending_id).needs_analysis = False
        db.session.commit()
        result = run_pending_analyses(limit=5, client=_fake_client())
        assert result["analyzed"] == 0


def test_pending_analyses_quota_stops_batch(app, ctx):
    with app.app_context():
        result = run_pending_analyses(limit=5, client=_raising_client(GeminiQuotaError("cota")))
        assert result["analyzed"] == 0
        # post continua pendente pra próxima rodada
        assert db.session.get(Post, ctx.pending_id).needs_analysis is True


def test_pending_analyses_skips_when_gemini_not_configured(app, ctx):
    # TestConfig não tem GEMINI_API_KEY → GeminiClient() levanta NotConfigured.
    with app.app_context():
        result = run_pending_analyses(limit=5, client=None)
        assert result.get("skipped") == "gemini_not_configured"
        assert db.session.get(Post, ctx.pending_id).needs_analysis is True


# --------------------------------------------------------------------------
# cleanup_expired_tokens
# --------------------------------------------------------------------------
def test_cleanup_removes_expired_states(app, ctx):
    with app.app_context():
        now = datetime.now(timezone.utc)
        db.session.add(OAuthState(provider=OAuthProvider.GOOGLE, state_token="expired",
                                  expires_at=now - timedelta(hours=1)))
        db.session.add(OAuthState(provider=OAuthProvider.GOOGLE, state_token="valid",
                                  expires_at=now + timedelta(hours=1)))
        db.session.commit()

        result = run_cleanup_expired_tokens()
        assert result["removed"] == 1

        remaining = db.session.scalars(select(OAuthState.state_token)).all()
        assert "valid" in remaining
        assert "expired" not in remaining
