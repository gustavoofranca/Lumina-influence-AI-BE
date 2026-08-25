"""Agregações de métricas pra alimentar os endpoints do dashboard (B5).

Tudo é computado a partir dos dados reais (Posts + AIAnalyses) seedados na B2.
Filtragem de período é feita em Python (volume pequeno) pra ser portável entre
Postgres (prod/dev) e SQLite (testes), evitando armadilhas de timezone no SQL.

KPIs financeiros (ROI, CAC) são *proxies* derivados — ver ADR-002. Não temos
dados de receita/conversão reais nesta fase, então estimamos via media value.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import (
    AIAnalysis,
    Influencer,
    Post,
    SocialAccount,
)

# --- Constantes dos proxies financeiros (ver ADR-002) ---
# EMV (earned media value) por engajamento — método padrão em marketing de
# influência (cada interação tem um valor de mídia atribuído). R$ 2,50/interação
# fica na faixa de benchmark de criadores mid/premium.
ENGAGEMENT_VALUE_CENTS = 250
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


# ==========================================================================
# Helpers de normalização temporal
# ==========================================================================
def _as_aware(dt: datetime) -> datetime:
    """Normaliza datetime pra aware-UTC (SQLite devolve naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def period_to_days(period: str | None) -> int:
    return PERIOD_DAYS.get((period or "30d").lower(), 30)


# ==========================================================================
# Coleta base de posts/análises por agência
# ==========================================================================
def fetch_agency_posts(
    agency_id: uuid.UUID,
    *,
    since: datetime | None = None,
    campaign_id: uuid.UUID | None = None,
) -> list[Post]:
    stmt = (
        select(Post)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == agency_id)
        .options(selectinload(Post.social_account))
    )
    if campaign_id is not None:
        stmt = stmt.where(Post.campaign_id == campaign_id)
    posts = list(db.session.scalars(stmt).all())
    if since is not None:
        posts = [p for p in posts if _as_aware(p.posted_at) >= since]
    return posts


def fetch_influencer_posts(influencer_id: uuid.UUID, *, limit: int | None = None) -> list[Post]:
    stmt = (
        select(Post)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .where(SocialAccount.influencer_id == influencer_id)
        .options(selectinload(Post.social_account))
        .order_by(Post.posted_at.desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(db.session.scalars(stmt).all())


def fetch_posts_by_influencer(
    influencer_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[Post]]:
    """Posts de vários influencers em uma query, agrupados por dono.

    A versão por influencer multiplica idas ao banco. Com Postgres local isso
    passa batido; com instância gerenciada, cada ida custa a latência da rede e
    a listagem enriquecida levava 13s.
    """
    if not influencer_ids:
        return {}

    rows = db.session.execute(
        select(SocialAccount.influencer_id, Post)
        .join(Post, Post.social_account_id == SocialAccount.id)
        .where(SocialAccount.influencer_id.in_(influencer_ids))
        .order_by(Post.posted_at.desc())
    ).all()

    agrupado: dict[uuid.UUID, list[Post]] = {i: [] for i in influencer_ids}
    for influencer_id, post in rows:
        agrupado[influencer_id].append(post)
    return agrupado


def fetch_analyses_by_influencer(
    influencer_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[AIAnalysis]]:
    """Análises de vários influencers em uma query, agrupadas por dono."""
    if not influencer_ids:
        return {}

    rows = db.session.execute(
        select(SocialAccount.influencer_id, AIAnalysis)
        .join(Post, Post.social_account_id == SocialAccount.id)
        .join(AIAnalysis, AIAnalysis.post_id == Post.id)
        .where(SocialAccount.influencer_id.in_(influencer_ids))
        .order_by(AIAnalysis.analyzed_at.desc())
    ).all()

    agrupado: dict[uuid.UUID, list[AIAnalysis]] = {i: [] for i in influencer_ids}
    for influencer_id, analise in rows:
        agrupado[influencer_id].append(analise)
    return agrupado


def fetch_influencer_analyses(influencer_id: uuid.UUID) -> list[AIAnalysis]:
    stmt = (
        select(AIAnalysis)
        .join(Post, AIAnalysis.post_id == Post.id)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .where(SocialAccount.influencer_id == influencer_id)
        .order_by(AIAnalysis.analyzed_at.desc())
    )
    return list(db.session.scalars(stmt).all())


# ==========================================================================
# Métricas por post / engajamento
# ==========================================================================
def _post_engagement(p: Post) -> int:
    return (p.likes or 0) + (p.comments_count or 0) + (p.shares or 0) + (p.saves or 0)


def engagement_rate(posts: list[Post]) -> float:
    """Engajamento médio (%) = média de (interações / reach_total) por post."""
    rates = []
    for p in posts:
        if p.reach_total and p.reach_total > 0:
            rates.append(_post_engagement(p) / p.reach_total)
    if not rates:
        return 0.0
    return round(sum(rates) / len(rates) * 100, 2)


def reach_split(posts: list[Post]) -> dict:
    organic = sum(p.reach_organic or 0 for p in posts)
    paid = sum(p.reach_paid or 0 for p in posts)
    total = organic + paid
    return {
        "organic": organic,
        "paid": paid,
        "total": total,
        "organic_pct": round(organic / total * 100, 1) if total else 0.0,
        "paid_pct": round(paid / total * 100, 1) if total else 0.0,
    }


# ==========================================================================
# Agregados de IA por influencer
# ==========================================================================
def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def ai_aggregates(analyses: list[AIAnalysis]) -> dict:
    """Médias de sentimento, coerência e bot a partir das análises do influencer."""
    if not analyses:
        return {
            "sentiment_score": None,
            "sentiment_index_pct": None,
            "brand_coherence": None,
            "bot_probability": None,
            "script_score": None,
            "analyses_count": 0,
        }
    sentiment = _avg([a.sentiment_score for a in analyses])  # -1..1
    return {
        "sentiment_score": sentiment,
        # índice 0..100 derivado do score -1..1
        "sentiment_index_pct": round((sentiment + 1) / 2 * 100, 1) if sentiment is not None else None,
        "brand_coherence": _avg([a.brand_coherence_score for a in analyses]),
        "bot_probability": _avg([a.bot_probability for a in analyses]),
        "script_score": _avg([a.script_score for a in analyses]),
        "analyses_count": len(analyses),
    }


def safety_rating(brand_coherence: float | None, sentiment_index: float | None, bot_prob: float | None) -> str:
    """Letra A-D a partir de coerência, sentimento e (inverso de) bot probability."""
    if brand_coherence is None or sentiment_index is None or bot_prob is None:
        return "N/A"
    score = (brand_coherence + sentiment_index + (100 - bot_prob)) / 3
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def resonance_score(engagement_pct: float, sentiment_index: float | None, brand_coherence: float | None) -> float:
    """Score 0-100 composto: engajamento (normalizado), sentimento e coerência.

    engagement_pct tipicamente 0-12% → normaliza dividindo por 12 e *100 (cap 100).
    """
    eng_norm = min(engagement_pct / 12 * 100, 100)
    parts = [eng_norm]
    if sentiment_index is not None:
        parts.append(sentiment_index)
    if brand_coherence is not None:
        parts.append(brand_coherence)
    return round(sum(parts) / len(parts), 1)


def viral_potential(resonance: float) -> str:
    if resonance >= 82:
        return "high"
    if resonance >= 65:
        return "medium"
    return "low"


# ==========================================================================
# KPIs financeiros (proxies — ADR-002)
# ==========================================================================
def estimated_media_value_cents(posts: list[Post]) -> int:
    """EMV = total de engajamentos * valor por engajamento (método de influência)."""
    total_eng = sum(_post_engagement(p) for p in posts)
    return int(total_eng * ENGAGEMENT_VALUE_CENTS)


def roi_proxy(posts: list[Post], cost_cents: int) -> float | None:
    """ROI% = (EMV - custo) / custo * 100. None se sem custo."""
    if not cost_cents:
        return None
    emv = estimated_media_value_cents(posts)
    return round((emv - cost_cents) / cost_cents * 100, 1)


def cac_proxy_cents(posts: list[Post], cost_cents: int) -> int | None:
    """CAC proxy = custo / (engajamentos totais). Custo por interação."""
    total_eng = sum(_post_engagement(p) for p in posts)
    if not total_eng or not cost_cents:
        return None
    return int(cost_cents / total_eng)


# ==========================================================================
# Growth trajectory (séries temporais por bucket)
# ==========================================================================
def growth_trajectory(posts: list[Post], period: str) -> list[dict]:
    """Agrupa reach organic/paid em buckets conforme o período.

    7d  → por dia (7 buckets)
    30d → por semana (S1-S4/5)
    90d → por mês (3 buckets)
    """
    days = period_to_days(period)
    now = datetime.now(timezone.utc)

    def bucket_key(dt: datetime):
        delta_days = (now - _as_aware(dt)).days
        if days <= 7:
            d = _as_aware(dt)
            return d.strftime("%d/%m")
        if days <= 30:
            week = delta_days // 7
            return f"S{max(1, 5 - week)}"
        # 90d → mês
        return _as_aware(dt).strftime("%b")

    buckets: dict[str, dict] = defaultdict(lambda: {"organic": 0, "paid": 0})
    order: list[str] = []
    # Ordena por data crescente pra labels saírem em ordem
    for p in sorted(posts, key=lambda x: _as_aware(x.posted_at)):
        k = bucket_key(p.posted_at)
        if k not in buckets:
            order.append(k)
        buckets[k]["organic"] += p.reach_organic or 0
        buckets[k]["paid"] += p.reach_paid or 0

    return [{"x": k, "organic": buckets[k]["organic"], "paid": buckets[k]["paid"]} for k in order]
