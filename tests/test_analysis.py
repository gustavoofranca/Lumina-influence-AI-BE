"""Testes da análise IA (B6) — parsing tolerante + endpoint com Gemini mockado."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

import src.services.ai_analysis_service as svc
from src.extensions import db
from src.integrations.gemini import GeminiError, GeminiQuotaError, GeminiResult
from src.models import (
    AIAnalysis,
    Agency,
    ApiUsageLog,
    Comment,
    Influencer,
    Post,
    PostType,
    SocialAccount,
    Platform,
    User,
    UserRole,
)
from src.models._enums import OAuthProvider
from src.services.ai_analysis_service import AnalysisParseError, parse_analysis_payload
from src.utils.jwt_utils import issue_token_pair


GOOD_JSON = """{
  "sentiment_score": 0.7,
  "sentiment_label": "positive",
  "sentiment_breakdown": {"technical_enthusiasm": 42, "purchase_intent": 28, "value_skepticism": 12, "neutral": 18},
  "script_score": 8.5,
  "brand_coherence_score": 91,
  "bot_probability": 5,
  "key_phrases": ["qualidade", "entrega rápida"],
  "recommendations": [{"priority": "high", "title": "Aumentar budget", "description": "Performance ótima"}]
}"""


# ==========================================================================
# Fakes de GeminiClient
# ==========================================================================
def _fake_client(text, tokens=120):
    class _Fake:
        def __init__(self, *a, **k):
            pass

        def generate_json(self, prompt):
            return GeminiResult(text=text, total_tokens=tokens, model="gemini-2.0-flash")

    return _Fake


def _raising_client(exc):
    class _Fake:
        def __init__(self, *a, **k):
            pass

        def generate_json(self, prompt):
            raise exc

    return _Fake


# ==========================================================================
# Fixture: agência + post com comentários (+ segunda agência p/ isolamento)
# ==========================================================================
class Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        for model in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(model).delete()
        db.session.commit()

        agency_a = Agency(name="Ag A")
        agency_b = Agency(name="Ag B")
        db.session.add_all([agency_a, agency_b])
        db.session.flush()

        def mk_user(email, role, agency):
            u = User(email=email, name=email, oauth_provider=OAuthProvider.GOOGLE,
                     oauth_id=f"o-{email}", role=role, agency=agency)
            db.session.add(u)
            return u

        admin = mk_user("admin@a.com", UserRole.ADMIN, agency_a)
        viewer = mk_user("viewer@a.com", UserRole.VIEWER, agency_a)
        b_admin = mk_user("admin@b.com", UserRole.ADMIN, agency_b)

        inf_a = Influencer(agency=agency_a, display_name="Inf A", niche="tech")
        inf_b = Influencer(agency=agency_b, display_name="Inf B", niche="food")
        db.session.add_all([inf_a, inf_b])
        db.session.flush()

        sa_a = SocialAccount(influencer=inf_a, platform=Platform.INSTAGRAM, handle="infa")
        sa_b = SocialAccount(influencer=inf_b, platform=Platform.TIKTOK, handle="infb")
        db.session.add_all([sa_a, sa_b])
        db.session.flush()

        def mk_post(sa, idx):
            return Post(
                social_account=sa, platform_post_id=f"{sa.platform.value}-{idx}",
                post_type=PostType.REEL, posted_at=datetime.now(timezone.utc),
                caption="Review do produto X", reach_total=100000, reach_organic=70000,
                reach_paid=30000, impressions=150000, likes=8000, comments_count=400,
                shares=300, saves=500,
            )

        post_a = mk_post(sa_a, 1)
        post_b = mk_post(sa_b, 1)
        db.session.add_all([post_a, post_b])
        db.session.flush()

        for i in range(5):
            db.session.add(Comment(
                post=post_a, platform_comment_id=f"c{i}", content=f"Comentário {i}",
                author_handle=f"u{i}", posted_at=datetime.now(timezone.utc), like_count=i,
            ))
        db.session.commit()

        c = Ctx()
        c.post_a_id = str(post_a.id)
        c.post_b_id = str(post_b.id)
        c.agency_a_id = str(agency_a.id)
        c.inf_a_id = inf_a.id
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.h_viewer = {"Authorization": f"Bearer {issue_token_pair(viewer)['access_token']}"}
        c.h_b = {"Authorization": f"Bearer {issue_token_pair(b_admin)['access_token']}"}
        yield c

        for model in (AIAnalysis, ApiUsageLog, Comment, Post, SocialAccount, Influencer, User, Agency):
            db.session.query(model).delete()
        db.session.commit()


# ==========================================================================
# Parsing tolerante (unit)
# ==========================================================================
def test_parse_clean_json():
    p = parse_analysis_payload(GOOD_JSON)
    assert p["sentiment_score"] == 0.7
    assert p["sentiment_label"].value == "positive"
    assert p["script_score"] == 8.5
    assert p["key_phrases"] == ["qualidade", "entrega rápida"]
    assert p["recommendations"][0]["priority"] == "high"


def test_parse_markdown_fenced():
    fenced = "```json\n" + GOOD_JSON + "\n```"
    p = parse_analysis_payload(fenced)
    assert p["brand_coherence_score"] == 91


def test_parse_with_surrounding_text():
    noisy = "Claro! Aqui está a análise:\n" + GOOD_JSON + "\nEspero ter ajudado."
    p = parse_analysis_payload(noisy)
    assert p["bot_probability"] == 5


def test_parse_clamps_out_of_range():
    bad = '{"sentiment_score": 5, "sentiment_label": "positive", "script_score": 99, "brand_coherence_score": 500, "bot_probability": -10}'
    p = parse_analysis_payload(bad)
    assert p["sentiment_score"] == 1  # clamped a 1
    assert p["script_score"] == 10
    assert p["brand_coherence_score"] == 100
    assert p["bot_probability"] == 0


def test_parse_derives_invalid_label():
    bad = '{"sentiment_score": -0.8, "sentiment_label": "muito_ruim"}'
    p = parse_analysis_payload(bad)
    assert p["sentiment_label"].value == "negative"


def test_parse_non_json_raises():
    with pytest.raises(AnalysisParseError):
        parse_analysis_payload("desculpe, não consigo analisar isso")


# ==========================================================================
# Endpoint POST /posts/:id/analyze
# ==========================================================================
def test_analyze_persists_new_analysis(client, ctx, app, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client(GOOD_JSON, tokens=222))

    r = client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 201, r.get_json()
    data = r.get_json()["data"]
    assert data["sentiment_label"] == "positive"
    assert data["brand_coherence_score"] == 91
    assert data["model_version"] == "gemini-2.0-flash"

    with app.app_context():
        count = db.session.scalar(
            select(func.count(AIAnalysis.id)).where(AIAnalysis.post_id == uuid.UUID(ctx.post_a_id))
        )
        assert count == 1
        # ApiUsageLog registrado com tokens
        log = db.session.scalar(select(ApiUsageLog))
        assert log is not None
        assert log.tokens_used == 222


def test_analyze_always_creates_new(client, ctx, app, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client(GOOD_JSON))
    client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    with app.app_context():
        count = db.session.scalar(
            select(func.count(AIAnalysis.id)).where(AIAnalysis.post_id == uuid.UUID(ctx.post_a_id))
        )
        assert count == 2  # versionado: sempre nova


def test_analyze_history_endpoint(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client(GOOD_JSON))
    client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    r = client.get(f"/api/v1/posts/{ctx.post_a_id}/analyses", headers=ctx.h_admin)
    assert r.status_code == 200
    assert len(r.get_json()["data"]) == 1


def test_analyze_viewer_forbidden(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client(GOOD_JSON))
    r = client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_viewer)
    assert r.status_code == 403


def test_analyze_other_agency_404(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client(GOOD_JSON))
    # admin da agência A tentando analisar post da agência B
    r = client.post(f"/api/v1/posts/{ctx.post_b_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 404


def test_analyze_quota_error_maps_429(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _raising_client(GeminiQuotaError("cota")))
    r = client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 429
    assert r.get_json()["error"]["code"] == "gemini_quota_exceeded"


def test_analyze_gemini_error_maps_502(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _raising_client(GeminiError("falhou")))
    r = client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 502


def test_analyze_bad_json_maps_502(client, ctx, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client("não é json"))
    r = client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    assert r.status_code == 502
    assert r.get_json()["error"]["code"] == "analysis_parse_error"


def test_analyze_no_analysis_persisted_on_failure(client, ctx, app, monkeypatch):
    monkeypatch.setattr(svc, "GeminiClient", _fake_client("lixo não-json"))
    client.post(f"/api/v1/posts/{ctx.post_a_id}/analyze", headers=ctx.h_admin)
    with app.app_context():
        count = db.session.scalar(select(func.count(AIAnalysis.id)))
        assert count == 0  # parse falhou antes de persistir


# ==========================================================================
# A faixa suspeita passou a ser medida, e não derivada
# ==========================================================================
def test_prompt_pede_a_faixa_suspeita_e_explica_a_diferenca():
    """O modelo precisa saber que são duas faixas distintas.

    Sem a regra, "suspeito" e "bot" viram sinônimos na cabeça do modelo e os
    dois números passam a dizer a mesma coisa — que é o problema anterior com
    outra roupa.
    """
    from src.services.ai_analysis_service import PROMPT_TEMPLATE

    assert '"suspicious_probability"' in PROMPT_TEMPLATE
    assert "não se sobrepõem" in PROMPT_TEMPLATE
    assert "automação clara" in PROMPT_TEMPLATE


def _analise_com_faixas(app, ctx, *, bot, suspeita):
    """Cria a análise do post A com as duas faixas e devolve a leitura da API."""
    from src.models import SentimentLabel
    from src.services import dashboard_service

    with app.app_context():
        db.session.add(AIAnalysis(
            post_id=uuid.UUID(ctx.post_a_id), model_version="teste",
            sentiment_score=0.5, sentiment_label=SentimentLabel.POSITIVE,
            bot_probability=bot, suspicious_probability=suspeita,
        ))
        db.session.commit()
        criador = db.session.get(Influencer, ctx.inf_a_id)
        return dashboard_service.influencer_analysis(criador)["audience_integrity"]


def test_audiencia_usa_a_faixa_medida_e_nao_a_constante(app, ctx):
    """Antes: suspeito = bot × 0,6 e bot = bot × 0,4. Agora os dois são medidos."""
    aud = _analise_com_faixas(app, ctx, bot=10.0, suspeita=25.0)
    assert aud["bots"] == 10.0
    assert aud["suspicious"] == 25.0
    assert aud["organic"] == 65.0


def test_analise_antiga_sem_a_faixa_nao_inventa_composicao(app, ctx):
    aud = _analise_com_faixas(app, ctx, bot=12.0, suspeita=None)
    assert aud["bots"] == 12.0
    # Preencher com qualquer número reintroduziria a invenção removida.
    assert aud["suspicious"] is None
    assert aud["totals"]["suspicious"] is None
    # E o orgânico é só o que sobra do que foi medido.
    assert aud["organic"] == 88.0


def test_faixas_incoerentes_omitem_a_composicao(app, ctx):
    """Modelo devolvendo faixas que somam mais de 100.

    Normalizar inventaria uma divisão; o honesto é não afirmar composição
    nenhuma e reclamar no log.
    """
    aud = _analise_com_faixas(app, ctx, bot=70.0, suspeita=60.0)
    assert aud["bots"] is None
    assert aud["suspicious"] is None
    assert aud["organic"] is None


def test_contagem_de_seguidores_acompanha_a_faixa_medida(app, ctx):
    aud = _analise_com_faixas(app, ctx, bot=10.0, suspeita=20.0)
    # A conta social do seed do teste não tem seguidor, então o que importa
    # aqui é o tipo: número onde houve medição, nulo onde não houve.
    assert isinstance(aud["totals"]["bots"], int)
    assert isinstance(aud["totals"]["suspicious"], int)
