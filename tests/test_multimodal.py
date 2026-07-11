"""Testes da análise multimodal (B9) — fetcher de vídeo + Gemini multimodal mockados."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

import src.services.ai_analysis_service as svc
from src.extensions import db
from src.integrations.base import OAuthTokenBundle  # noqa: F401 (garante import chain)
from src.integrations.gemini import GeminiResult
from src.integrations.media import VideoAsset, VideoFetchError, VideoFetcher
from src.models import (
    AIAnalysis,
    Agency,
    ApiUsageLog,
    Comment,
    Influencer,
    OAuthProvider,
    Platform,
    Post,
    PostType,
    SocialAccount,
    User,
    UserRole,
)
from src.services.ai_analysis_service import parse_analysis_payload
from src.utils.jwt_utils import issue_token_pair


MULTIMODAL_JSON = (
    '{"transcript_text":"Olha esse gadget, testei por semanas e vale muito.",'
    '"sentiment_score":0.8,"sentiment_label":"positive",'
    '"sentiment_breakdown":{"technical_enthusiasm":45,"purchase_intent":30,"value_skepticism":10,"neutral":15},'
    '"script_score":9,"brand_coherence_score":94,"bot_probability":4,'
    '"key_phrases":["vale muito","testei"],"recommendations":[{"priority":"high","title":"X","description":"Y"}]}'
)


# ==========================================================================
# Fakes
# ==========================================================================
class FakeFetcher(VideoFetcher):
    def __init__(self):
        self.fetched = False
        self.cleaned = False

    def fetch(self, video_url):
        if not video_url:
            raise VideoFetchError("sem url")
        self.fetched = True
        return VideoAsset(path="/tmp/fake.mp4", mime_type="video/mp4")

    def cleanup(self, asset):
        self.cleaned = True


class RaisingFetcher(VideoFetcher):
    def fetch(self, video_url):
        raise VideoFetchError("download falhou")


def _fake_gemini(text=MULTIMODAL_JSON, tokens=500):
    class _Fake:
        def __init__(self, *a, **k):
            pass

        def generate_json_with_video(self, prompt, video_path, mime_type="video/mp4"):
            return GeminiResult(text=text, total_tokens=tokens, model="gemini-2.5-flash")

    return _Fake()


# ==========================================================================
# Parsing — transcript_text
# ==========================================================================
def test_parse_extracts_transcript():
    p = parse_analysis_payload(MULTIMODAL_JSON)
    assert p["transcript_text"].startswith("Olha esse gadget")


def test_parse_text_only_has_no_transcript():
    p = parse_analysis_payload('{"sentiment_score":0.1,"sentiment_label":"neutral"}')
    assert p["transcript_text"] is None


# ==========================================================================
# Fixture
# ==========================================================================
class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for m in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()

        agency = Agency(name="Ag")
        db.session.add(agency)
        db.session.flush()
        admin = User(email="a@a.com", name="A", oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id="o", role=UserRole.ADMIN, agency=agency)
        db.session.add(admin)
        inf = Influencer(agency=agency, display_name="Inf", niche="tech")
        db.session.add(inf)
        db.session.flush()
        sa = SocialAccount(influencer=inf, platform=Platform.YOUTUBE, handle="canal")
        db.session.add(sa)
        db.session.flush()

        reel = Post(social_account=sa, platform_post_id="reel-1", post_type=PostType.REEL,
                    posted_at=datetime.now(timezone.utc), caption="review",
                    video_url="https://cdn.example/reel-1.mp4", reach_total=1000,
                    reach_organic=800, reach_paid=200, impressions=1500, likes=100,
                    comments_count=10, shares=5, saves=8)
        image = Post(social_account=sa, platform_post_id="img-1", post_type=PostType.IMAGE,
                     posted_at=datetime.now(timezone.utc), caption="foto", video_url=None,
                     reach_total=500, reach_organic=400, reach_paid=100, impressions=700,
                     likes=50, comments_count=5, shares=2, saves=3)
        db.session.add_all([reel, image])
        db.session.flush()
        db.session.add(Comment(post=reel, platform_comment_id="c1", content="top",
                               author_handle="u", posted_at=datetime.now(timezone.utc)))
        db.session.commit()

        c = Ctx()
        c.reel_id = str(reel.id)
        c.image_id = str(image.id)
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        yield c

        for m in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(m).delete()
        db.session.commit()


# ==========================================================================
# Endpoint ?multimodal=true
# ==========================================================================
def test_multimodal_persists_transcript(client, ctx, app, monkeypatch):
    fake_fetcher = FakeFetcher()
    monkeypatch.setattr(svc, "GeminiClient", lambda *a, **k: _fake_gemini())
    monkeypatch.setattr(
        "src.integrations.media.HttpVideoFetcher", lambda *a, **k: fake_fetcher
    )

    r = client.post(f"/api/v1/posts/{ctx.reel_id}/analyze?multimodal=true", headers=ctx.h_admin)
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert data["transcript_text"].startswith("Olha esse gadget")
    assert data["model_version"].endswith("-multimodal")
    assert data["brand_coherence_score"] == 94

    # vídeo foi baixado e o temp limpo
    assert fake_fetcher.fetched is True
    assert fake_fetcher.cleaned is True

    with app.app_context():
        a = db.session.scalar(select(AIAnalysis))
        assert a.transcript_text is not None
        assert db.session.scalar(select(func.count(ApiUsageLog.id))) == 1


def test_multimodal_on_image_post_422(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", lambda *a, **k: _fake_gemini())
    monkeypatch.setattr("src.integrations.media.HttpVideoFetcher", lambda *a, **k: FakeFetcher())

    r = client.post(f"/api/v1/posts/{ctx.image_id}/analyze?multimodal=true", headers=ctx.h_admin)
    assert r.status_code == 422
    assert "vídeo" in r.get_json()["error"]["message"].lower()


def test_multimodal_video_fetch_failure_502(client, ctx, app, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", lambda *a, **k: _fake_gemini())
    monkeypatch.setattr("src.integrations.media.HttpVideoFetcher", lambda *a, **k: RaisingFetcher())

    r = client.post(f"/api/v1/posts/{ctx.reel_id}/analyze?multimodal=true", headers=ctx.h_admin)
    assert r.status_code == 502
    assert r.get_json()["error"]["code"] == "video_fetch_error"

    with app.app_context():
        # falha antes de persistir
        assert db.session.scalar(select(func.count(AIAnalysis.id))) == 0


def test_text_analysis_still_works_without_multimodal(client, ctx, monkeypatch):
    """Sanidade: o caminho texto (sem ?multimodal) continua funcionando."""
    class _FakeText:
        def __init__(self, *a, **k):
            pass

        def generate_json(self, prompt):
            return GeminiResult(
                text='{"sentiment_score":0.5,"sentiment_label":"positive"}',
                total_tokens=80, model="gemini-2.5-flash",
            )

    monkeypatch.setattr(svc, "GeminiClient", lambda *a, **k: _FakeText())
    r = client.post(f"/api/v1/posts/{ctx.reel_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["transcript_text"] is None
    assert not data["model_version"].endswith("-multimodal")
