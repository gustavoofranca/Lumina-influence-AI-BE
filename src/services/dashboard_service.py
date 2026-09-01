"""Composição dos dados de dashboard a partir do metric_service.

Espelha a estrutura dos mocks do front (dashboard.js, analise.js, campanhas.js),
em snake_case (convenção da API). O front mapeia os nomes na B11.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import (
    AIAnalysis,
    Campaign,
    CampaignInfluencer,
    Influencer,
    InfluencerStatus,
    Post,
    RecommendationDecision,
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

    # Sem post no período não há engajamento medido — e zero afirmaria que houve
    # medição e deu zero (ADR-003). O próprio engagement_rate já devolve None.
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

    # Cada pill leva o número que a justifica. Sem isso a interface precisava
    # escrever o valor no rótulo, e escrevia um fixo: "85% Positive Sentiment"
    # aparecia para qualquer criador, inclusive os de sentimento 66%.
    pills = []
    if post.retention_rate is not None and post.retention_rate >= 0.6:
        pills.append({
            "key": "high_retention",
            "variant": "success",
            "value_pct": round(post.retention_rate * 100, 1),
        })
    if analysis.sentiment_label and analysis.sentiment_label.value == "positive":
        pills.append({
            "key": "positive_sentiment",
            "variant": "success",
            "value_pct": M.sentiment_to_pct(analysis.sentiment_score),
        })
    if analysis.bot_probability is not None and analysis.bot_probability >= 15:
        pills.append({
            "key": "bot_alert",
            "variant": "danger",
            "value_pct": round(analysis.bot_probability, 1),
        })

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
def _influencer_scorecard(
    influencer: Influencer,
    *,
    since: datetime | None = None,
    posts=None,
    analyses=None,
) -> dict:
    """Cartão de um criador.

    `posts` e `analyses` podem vir de uma busca em lote — mesma convenção de
    `influencer_metrics`. Sem isso, montar a lista inteira custa três queries
    por criador.
    """
    posts = M.fetch_influencer_posts(influencer.id) if posts is None else posts
    if since is not None:
        posts = [p for p in posts if M._as_aware(p.posted_at) >= since]
    if analyses is None:
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


def influencer_metrics(influencer: Influencer, *, posts=None, analyses=None) -> dict:
    """Métricas computadas de um influencer (pra enriquecer a listagem do front).

    `posts` e `analyses` podem vir prontos de uma busca em lote — é o que evita
    N+1 quando a listagem enriquece vários influencers de uma vez.
    """
    posts = M.fetch_influencer_posts(influencer.id) if posts is None else posts
    analyses = M.fetch_influencer_analyses(influencer.id) if analyses is None else analyses
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


def influencer_metrics_bulk(influencers: list[Influencer]) -> dict[str, dict]:
    """Métricas de vários influencers com duas queries no total, não duas por um."""
    ids = [inf.id for inf in influencers]
    posts_por_inf = M.fetch_posts_by_influencer(ids)
    analises_por_inf = M.fetch_analyses_by_influencer(ids)
    return {
        str(inf.id): influencer_metrics(
            inf,
            posts=posts_por_inf.get(inf.id, []),
            analyses=analises_por_inf.get(inf.id, []),
        )
        for inf in influencers
    }


def top_performing(agency_id: uuid.UUID, *, period: str = "30d", limit: int = 6) -> list[dict]:
    # Três buscas no total — posts, análises e contas sociais — em vez de três
    # por criador. Cada query é um round trip, e contra banco remoto era isso
    # que fazia o overview levar 15s (relatório em docs/testes/carga.md).
    influencers = db.session.scalars(
        select(Influencer)
        .where(Influencer.agency_id == agency_id)
        .options(selectinload(Influencer.social_accounts))
    ).all()
    ids = [inf.id for inf in influencers]
    posts_por_inf = M.fetch_posts_by_influencer(ids)
    analises_por_inf = M.fetch_analyses_by_influencer(ids)
    cards = [
        _influencer_scorecard(
            inf,
            posts=posts_por_inf.get(inf.id, []),
            analyses=analises_por_inf.get(inf.id, []),
        )
        for inf in influencers
    ]
    # Quem não tem métrica medida vai para o fim do ranking, em vez de ser
    # comparado como se tivesse pontuado zero.
    cards.sort(
        key=lambda c: (c["resonance_score"] is not None, c["resonance_score"] or 0),
        reverse=True,
    )
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
def influencer_analysis_history(influencer: Influencer) -> list[dict]:
    """Histórico de análises do criador, da mais recente para a mais antiga.

    Uma análise é sempre de um post; o histórico do criador é a união das
    análises de todos os posts das contas dele. O `scope` diz de que plataforma
    e formato veio cada uma, porque duas análises no mesmo dia costumam ser de
    peças diferentes.
    """
    analyses = M.fetch_influencer_analyses(influencer.id)
    if not analyses:
        return []

    posts = {
        p.id: p
        for p in db.session.scalars(
            select(Post)
            .where(Post.id.in_([a.post_id for a in analyses]))
            .options(selectinload(Post.social_account))
        ).all()
    }
    historico = []
    for a in analyses:
        post = posts.get(a.post_id)
        plataforma = post.social_account.platform.value if post and post.social_account else None
        historico.append({
            "analysis_id": str(a.id),
            "post_id": str(a.post_id),
            "analyzed_at": a.analyzed_at.isoformat(),
            "platform": plataforma,
            "post_type": post.post_type.value if post else None,
            "brand_coherence": a.brand_coherence_score,
            "sentiment_index_pct": M.sentiment_to_pct(a.sentiment_score),
            "bot_probability": a.bot_probability,
            "script_score": a.script_score,
        })
    return historico


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

    # Audience integrity deriva do bot_probability médio. Sem análise não há de
    # onde derivar, e o cartão inteiro sai como ausente: tratar bot como 0
    # anunciava "100% de audiência orgânica" para quem nunca foi analisado —
    # uma afirmação favorável inventada, pior que um zero (ADR-003).
    bot = ai["bot_probability"]
    total_followers = sum(sa.follower_count for sa in influencer.social_accounts)
    audience_integrity = None
    if bot is not None:
        suspicious_pct = round(bot * 0.6, 1)
        bots_pct = round(bot * 0.4, 1)
        audiencia_organica_pct = round(100 - suspicious_pct - bots_pct, 1)
        audience_integrity = {
            "organic": audiencia_organica_pct,
            "suspicious": suspicious_pct,
            "bots": bots_pct,
            "totals": {
                "verified_humans": int(total_followers * audiencia_organica_pct / 100),
                "suspicious": int(total_followers * suspicious_pct / 100),
                "bots": int(total_followers * bots_pct / 100),
            },
        }

    # Neural confidence — só as dimensões efetivamente medidas. Lista vazia é o
    # que o cartão do front já espera para mostrar seu estado vazio.
    neural_bruto = [
        ("script_accuracy", None if ai["script_score"] is None else round(ai["script_score"] * 10, 1)),
        ("tone_matching", sentiment_index),
        ("demographic_sync", ai["brand_coherence"]),
    ]
    neural = [{"key": k, "value": v} for k, v in neural_bruto if v is not None]

    # Transcrição da análise mais recente que tenha uma. Nem toda análise
    # transcreve: só as multimodais, que leem o áudio do vídeo. As demais
    # analisam legenda e comentários, e não têm o que transcrever.
    transcript = None
    for a in analyses:
        if a.transcript_text:
            transcript = {
                "text": a.transcript_text,
                "analyzed_at": a.analyzed_at.isoformat(),
                "key_phrases": a.key_phrases or [],
            }
            break

    # Recomendações da análise mais recente, já com a decisão da agência.
    latest = analyses[0] if analyses else None
    recommendations = _recomendacoes_com_decisao(latest)
    latest_analysis_id = str(latest.id) if latest else None

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
        # Mesma série do dashboard, restrita aos posts deste criador. A aba
        # Visão Geral já tinha o gráfico montado e mostrava estado vazio
        # dizendo que a API não servia isto.
        "growth_trajectory": M.growth_trajectory(posts, "90d"),
        "sentiment_clusters": clusters,
        "keywords": keywords,
        "transcript": transcript,
        "audience_integrity": audience_integrity,
        "neural_confidence": neural,
        "recommendations": recommendations,
        "latest_analysis_id": latest_analysis_id,
        "analyses_count": ai["analyses_count"],
    }


def _recomendacoes_com_decisao(analysis) -> list[dict]:
    """Recomendações da análise, com o que a agência decidiu sobre cada uma.

    A decisão viaja **junto** com o item, e não numa chamada separada: sem isso
    a tela recarregada não tem como saber o que já foi decidido, e voltaria a
    oferecer "aceitar" para algo que a agência aceitou semana passada.

    `index` sai no payload porque é a identidade estável do item — a
    recomendação vive dentro do JSON da análise e não tem id próprio.
    """
    if analysis is None or not analysis.recommendations:
        return []

    decisoes = {
        d.item_index: d
        for d in db.session.scalars(
            select(RecommendationDecision).where(
                RecommendationDecision.analysis_id == analysis.id
            )
        )
    }
    saida = []
    for i, item in enumerate(analysis.recommendations):
        if not isinstance(item, dict):
            continue
        d = decisoes.get(i)
        saida.append({
            **item,
            "index": i,
            "decision": d.decision.value if d else None,
            "decided_at": d.updated_at.isoformat() if d and d.updated_at else None,
            # Nome de quem decidiu, e não só a decisão: auditoria em que
            # ninguém responde pelo aceite não é auditoria. Fica nulo quando o
            # usuário saiu da agência — o FK é SET NULL de propósito.
            "decided_by": d.decided_by.name if d and d.decided_by else None,
        })
    return saida


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
def campaign_benchmarking(
    campaign: Campaign,
    *,
    period_start=None,
    period_end=None,
) -> dict:
    """Comparativo entre os influencers da campanha.

    Sem período, considera toda a campanha (é o que a tela de detalhe mostra).
    Com período, restringe aos posts da janela — o relatório declara um
    intervalo na capa e precisa que os números sejam daquele intervalo.
    """
    links = db.session.scalars(
        select(CampaignInfluencer).where(CampaignInfluencer.campaign_id == campaign.id)
    ).all()

    def _in_period(post) -> bool:
        if period_start is None and period_end is None:
            return True
        posted = M._as_aware(post.posted_at).date()
        if period_start is not None and posted < period_start:
            return False
        if period_end is not None and posted > period_end:
            return False
        return True

    rows = []
    radar_series = []
    for link in links:
        influencer = db.session.get(Influencer, link.influencer_id)
        # Só o que é desta campanha. Sem fallback para o histórico completo:
        # atribuir posts de outra campanha a esta inflaria os números dela.
        posts = [
            p
            for p in M.fetch_influencer_posts(influencer.id)
            if p.campaign_id == campaign.id and _in_period(p)
        ]
        post_ids = {p.id for p in posts}
        analyses = [
            a for a in M.fetch_influencer_analyses(influencer.id) if a.post_id in post_ids
        ]
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
                # Dimensão sem medição vira null e o radar abre uma lacuna, em
                # vez de desenhar um vértice na origem como se fosse nota zero.
                "values": [
                    min(round(split["total"] / 10000), 100),  # reach normalizado
                    round(eng * 8, 1) if eng is not None else None,  # engajamento escalado
                    ai["sentiment_index_pct"],
                    ai["brand_coherence"],
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
