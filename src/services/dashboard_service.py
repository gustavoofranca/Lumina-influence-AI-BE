"""Composição dos dados de dashboard a partir do metric_service.

Espelha a estrutura dos mocks do front (dashboard.js, analise.js, campanhas.js),
em snake_case (convenção da API). O front mapeia os nomes na B11.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    AIAnalysis,
    Campaign,
    CampaignInfluencer,
    Influencer,
    InfluencerStatus,
    Post,
    SocialAccount,
)
from src.services import metric_service as M


def _change(curr: float | None, prev: float | None) -> dict:
    """Bloco de variação entre período atual e anterior."""
    if curr is None or prev is None:
        return {"change": None, "change_type": "neutral"}
    delta = round(curr - prev, 2)
    return {"change": delta, "change_type": "positive" if delta >= 0 else "negative"}


# ==========================================================================
# Dashboard overview
# ==========================================================================
def _agency_cost_cents(
    agency_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    *,
    window_start=None,
    window_end=None,
) -> int:
    """Custo atribuível. Com campaign_id, usa o orçamento da campanha. Sem ele e
    com janela, rateia cada orçamento pela fração de dias da campanha que cai
    dentro da janela (gasto proporcional ao período analisado)."""
    if campaign_id is not None:
        camp = db.session.get(Campaign, campaign_id)
        return int(camp.budget_brl_cents) if camp else 0

    campaigns = db.session.scalars(
        select(Campaign).where(Campaign.agency_id == agency_id)
    ).all()
    if window_start is None or window_end is None:
        return sum(int(c.budget_brl_cents) for c in campaigns)

    ws, we = window_start.date(), window_end.date()
    total = 0
    for c in campaigns:
        overlap_start = max(c.period_start, ws)
        overlap_end = min(c.period_end, we)
        overlap_days = (overlap_end - overlap_start).days + 1
        if overlap_days <= 0:
            continue
        camp_days = max((c.period_end - c.period_start).days + 1, 1)
        total += int(c.budget_brl_cents * overlap_days / camp_days)
    return total


def overview(agency_id: uuid.UUID, *, period: str = "30d", campaign_id: uuid.UUID | None = None) -> dict:
    days = M.period_to_days(period)
    now = datetime.now(timezone.utc)
    since_curr = now - timedelta(days=days)
    since_prev = now - timedelta(days=days * 2)

    posts_curr = M.fetch_agency_posts(agency_id, since=since_curr, campaign_id=campaign_id)
    # período anterior = [now-2d, now-d)
    all_prev = M.fetch_agency_posts(agency_id, since=since_prev, campaign_id=campaign_id)
    posts_prev = [p for p in all_prev if M._as_aware(p.posted_at) < since_curr]

    cost = _agency_cost_cents(
        agency_id, campaign_id, window_start=since_curr, window_end=now
    )

    eng_curr = M.engagement_rate(posts_curr)
    eng_prev = M.engagement_rate(posts_prev)
    roi_curr = M.roi_proxy(posts_curr, cost)
    roi_prev = M.roi_proxy(posts_prev, cost)
    cac_curr = M.cac_proxy_cents(posts_curr, cost)

    active = db.session.scalar(
        select(func.count(Influencer.id)).where(
            Influencer.agency_id == agency_id,
            Influencer.status == InfluencerStatus.ACTIVE,
        )
    )

    kpis = {
        "roi": {
            "value_pct": roi_curr,
            **_change(roi_curr, roi_prev),
        },
        "engagement_rate": {
            "value_pct": eng_curr,
            **_change(eng_curr, eng_prev),
        },
        "cac": {
            "value_brl_cents": cac_curr,
            "hint": "custo por interação (proxy)",
        },
        "active_influencers": {
            "value": int(active or 0),
        },
    }

    return {
        "kpis": kpis,
        "growth_trajectory": M.growth_trajectory(posts_curr, period),
        "featured_diagnosis": featured_diagnosis(agency_id),
        "top_performing": top_performing(agency_id, period=period, limit=6),
    }


# ==========================================================================
# Featured diagnosis (análise mais recente da agência)
# ==========================================================================
def featured_diagnosis(agency_id: uuid.UUID) -> dict | None:
    analysis = db.session.scalar(
        select(AIAnalysis)
        .join(Post, AIAnalysis.post_id == Post.id)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == agency_id)
        .order_by(AIAnalysis.analyzed_at.desc())
        .limit(1)
    )
    if analysis is None:
        return None

    post = db.session.get(Post, analysis.post_id)
    sa = db.session.get(SocialAccount, post.social_account_id)
    influencer = db.session.get(Influencer, sa.influencer_id)

    pills = []
    if post.retention_rate is not None and post.retention_rate >= 0.6:
        pills.append({"key": "high_retention", "variant": "success"})
    if analysis.sentiment_label and analysis.sentiment_label.value == "positive":
        pills.append({"key": "positive_sentiment", "variant": "success"})
    if analysis.bot_probability is not None and analysis.bot_probability >= 15:
        pills.append({"key": "bot_alert", "variant": "danger"})

    return {
        "influencer_id": str(influencer.id),
        "influencer_name": influencer.display_name,
        "analysis_id": str(analysis.id),
        "platform": sa.platform.value,
        "transcript": analysis.transcript_text,
        "pills": pills,
        "brand_coherence": analysis.brand_coherence_score,
        "thumbnail_url": post.thumbnail_url,
    }


# ==========================================================================
# Top performing networks
# ==========================================================================
def _influencer_scorecard(influencer: Influencer, *, since: datetime | None = None) -> dict:
    posts = M.fetch_influencer_posts(influencer.id)
    if since is not None:
        posts = [p for p in posts if M._as_aware(p.posted_at) >= since]
    analyses = M.fetch_influencer_analyses(influencer.id)

    eng = M.engagement_rate(posts)
    ai = M.ai_aggregates(analyses)
    resonance = M.resonance_score(eng, ai["sentiment_index_pct"], ai["brand_coherence"])
    accounts = influencer.social_accounts
    handle = f"@{accounts[0].handle}" if accounts else None
    followers = sum(sa.follower_count for sa in accounts)
    return {
        "influencer_id": str(influencer.id),
        "display_name": influencer.display_name,
        "niche": influencer.niche,
        "handle": handle,
        "followers": followers,
        "resonance_score": resonance,
        "viral_potential": M.viral_potential(resonance),
        "engagement_rate": eng,
        "status": influencer.status.value,
    }


def influencer_metrics(influencer: Influencer) -> dict:
    """Métricas computadas de um influencer (pra enriquecer a listagem do front)."""
    posts = M.fetch_influencer_posts(influencer.id)
    analyses = M.fetch_influencer_analyses(influencer.id)
    eng = M.engagement_rate(posts)
    ai = M.ai_aggregates(analyses)
    split = M.reach_split(posts)
    resonance = M.resonance_score(eng, ai["sentiment_index_pct"], ai["brand_coherence"])
    rating = M.safety_rating(ai["brand_coherence"], ai["sentiment_index_pct"], ai["bot_probability"])
    last_at = analyses[0].analyzed_at.isoformat() if analyses else None
    return {
        "engagement_rate": eng,
        "organic_pct": split["organic_pct"],
        "paid_pct": split["paid_pct"],
        "sentiment_index_pct": ai["sentiment_index_pct"],
        "brand_coherence": ai["brand_coherence"],
        "bot_probability": ai["bot_probability"],
        "safety_rating": rating,
        "resonance_score": resonance,
        "viral_potential": M.viral_potential(resonance),
        "last_analysis_at": last_at,
        "analyses_count": ai["analyses_count"],
    }


def top_performing(agency_id: uuid.UUID, *, period: str = "30d", limit: int = 6) -> list[dict]:
    influencers = db.session.scalars(
        select(Influencer).where(Influencer.agency_id == agency_id)
    ).all()
    cards = [_influencer_scorecard(inf) for inf in influencers]
    cards.sort(key=lambda c: c["resonance_score"], reverse=True)
    return cards[:limit]


# ==========================================================================
# Network density
# ==========================================================================
def network_density(agency_id: uuid.UUID) -> dict:
    total = db.session.scalar(
        select(func.count(Influencer.id)).where(Influencer.agency_id == agency_id)
    ) or 0
    connected = db.session.scalar(
        select(func.count(func.distinct(Influencer.id)))
        .select_from(Influencer)
        .join(SocialAccount, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == agency_id)
    ) or 0
    value = round(connected / total * 100) if total else 0
    return {"value": value, "total": int(total), "connected": int(connected)}


# ==========================================================================
# Influencer analysis (tela Diagnóstico IA)
# ==========================================================================
def influencer_analysis(influencer: Influencer) -> dict:
    analyses = M.fetch_influencer_analyses(influencer.id)
    posts = M.fetch_influencer_posts(influencer.id)
    ai = M.ai_aggregates(analyses)
    eng = M.engagement_rate(posts)
    split = M.reach_split(posts)

    sentiment_index = ai["sentiment_index_pct"]
    rating = M.safety_rating(ai["brand_coherence"], sentiment_index, ai["bot_probability"])

    # Sentiment clusters: média dos sentiment_breakdown das análises
    cluster_acc: Counter = Counter()
    cluster_n = 0
    key_phrase_counter: Counter = Counter()
    for a in analyses:
        if a.sentiment_breakdown:
            cluster_n += 1
            for k, v in a.sentiment_breakdown.items():
                cluster_acc[k] += v
        if a.key_phrases:
            for ph in a.key_phrases:
                key_phrase_counter[ph] += 1
    clusters = (
        [{"key": k, "value": round(v / cluster_n, 1)} for k, v in cluster_acc.most_common()]
        if cluster_n
        else []
    )
    keywords = [{"word": w, "weight": c} for w, c in key_phrase_counter.most_common(12)]

    # Audience integrity (derivado de bot_probability médio)
    bot = ai["bot_probability"] or 0
    suspicious_pct = round(bot * 0.6, 1)
    bots_pct = round(bot * 0.4, 1)
    organic_pct = round(100 - suspicious_pct - bots_pct, 1)
    total_followers = sum(sa.follower_count for sa in influencer.social_accounts)

    # Neural confidence
    neural = [
        {"key": "script_accuracy", "value": round((ai["script_score"] or 0) * 10, 1)},
        {"key": "tone_matching", "value": sentiment_index or 0},
        {"key": "demographic_sync", "value": ai["brand_coherence"] or 0},
    ]

    # Recomendações da análise mais recente
    recommendations = analyses[0].recommendations if analyses and analyses[0].recommendations else []
    latest_analysis_id = str(analyses[0].id) if analyses else None

    return {
        "influencer": {
            "id": str(influencer.id),
            "display_name": influencer.display_name,
            "niche": influencer.niche,
            "platforms": sorted({sa.platform.value for sa in influencer.social_accounts}),
            "total_followers": total_followers,
        },
        "diagnostic_kpis": {
            "brand_coherence": ai["brand_coherence"],
            "sentiment_index_pct": sentiment_index,
            "safety_rating": rating,
            "bot_probability": ai["bot_probability"],
        },
        "engagement_rate": eng,
        "reach_split": split,
        "sentiment_clusters": clusters,
        "keywords": keywords,
        "audience_integrity": {
            "organic": organic_pct,
            "suspicious": suspicious_pct,
            "bots": bots_pct,
            "totals": {
                "verified_humans": int(total_followers * organic_pct / 100),
                "suspicious": int(total_followers * suspicious_pct / 100),
                "bots": int(total_followers * bots_pct / 100),
            },
        },
        "neural_confidence": neural,
        "recommendations": recommendations,
        "latest_analysis_id": latest_analysis_id,
        "analyses_count": ai["analyses_count"],
    }


# ==========================================================================
# Influencer posts (tab Posts Analisados)
# ==========================================================================
def influencer_posts(influencer: Influencer, *, limit: int = 20) -> list[dict]:
    posts = M.fetch_influencer_posts(influencer.id, limit=limit)
    # Mapeia análise mais recente por post (pra sentiment/bot)
    analyses = M.fetch_influencer_analyses(influencer.id)
    latest_by_post: dict = {}
    for a in analyses:
        latest_by_post.setdefault(a.post_id, a)

    out = []
    for p in posts:
        a = latest_by_post.get(p.id)
        out.append(
            {
                "id": str(p.id),
                "caption": p.caption,
                "posted_at": p.posted_at.isoformat(),
                "platform": p.social_account.platform.value,
                "post_type": p.post_type.value,
                "reach_total": p.reach_total,
                "sentiment_score": a.sentiment_score if a else None,
                "bot_probability": a.bot_probability if a else None,
            }
        )
    return out


# ==========================================================================
# Campaign benchmarking
# ==========================================================================
def campaign_benchmarking(campaign: Campaign) -> dict:
    links = db.session.scalars(
        select(CampaignInfluencer).where(CampaignInfluencer.campaign_id == campaign.id)
    ).all()

    rows = []
    radar_series = []
    for link in links:
        influencer = db.session.get(Influencer, link.influencer_id)
        posts = [
            p for p in M.fetch_influencer_posts(influencer.id) if p.campaign_id == campaign.id
        ]
        if not posts:
            posts = M.fetch_influencer_posts(influencer.id)  # fallback: todos
        analyses = M.fetch_influencer_analyses(influencer.id)
        eng = M.engagement_rate(posts)
        ai = M.ai_aggregates(analyses)
        split = M.reach_split(posts)
        resonance = M.resonance_score(eng, ai["sentiment_index_pct"], ai["brand_coherence"])

        accounts = influencer.social_accounts
        rows.append(
            {
                "influencer_id": str(influencer.id),
                "display_name": influencer.display_name,
                "handle": f"@{accounts[0].handle}" if accounts else None,
                "niche": influencer.niche,
                "status": influencer.status.value,
                "platforms": [sa.platform.value for sa in accounts],
                "followers": sum(sa.follower_count for sa in accounts),
                "total_reach": split["total"],
                "organic_pct": split["organic_pct"],
                "paid_pct": split["paid_pct"],
                "engagement_rate": eng,
                "sentiment_index_pct": ai["sentiment_index_pct"],
                "brand_coherence": ai["brand_coherence"],
                "bot_probability": ai["bot_probability"],
                "ai_score": resonance,
                "posts_count": len(posts),
                "deliverables": link.deliverables,
                "cost_brl_cents": link.fee_brl_cents,
            }
        )
        radar_series.append(
            {
                "influencer_id": str(influencer.id),
                "name": influencer.display_name,
                "values": [
                    min(round(split["total"] / 10000), 100),  # reach normalizado
                    round(eng * 8, 1),  # engajamento escalado
                    ai["sentiment_index_pct"] or 0,
                    ai["brand_coherence"] or 0,
                    split["organic_pct"],
                ],
            }
        )

    return {
        "campaign": {
            "id": str(campaign.id),
            "brand_name": campaign.brand_name,
            "title": campaign.title,
            "status": campaign.status.value,
            "period_start": campaign.period_start.isoformat(),
            "period_end": campaign.period_end.isoformat(),
            "budget_brl_cents": campaign.budget_brl_cents,
        },
        "influencers": rows,
        "radar": {
            "dimensions": ["reach", "engagement", "sentiment", "coherence", "organic"],
            "series": radar_series,
        },
    }
