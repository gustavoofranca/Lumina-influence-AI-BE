"""Seed de dados realistas — popula o banco com dados que espelham os mocks do front.

Política:
- Fixtures estáticas em JSON pra entidades canônicas (plan, agency, users, influencers, campaigns, reports).
- Geração procedural determinística (random.seed) pra posts, comments e AI analyses.
- `seed_run()` é idempotente no nível de "Lumina Influence Agency" — se já existe, aborta.
- `seed_clear()` limpa todas as tabelas de domínio (preserva Alembic version).
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from src.extensions import db
from src.models import (
    AIAnalysis,
    Agency,
    ApiUsageLog,
    Campaign,
    CampaignInfluencer,
    CampaignStatus,
    Comment,
    Influencer,
    InfluencerStatus,
    OAuthProvider,
    OAuthState,
    Plan,
    Platform,
    Post,
    PostType,
    Report,
    ReportFormat,
    SentimentLabel,
    SocialAccount,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SEED_NAMESPACE = uuid.UUID("8c5d6e7a-1f2b-4a3c-9d4e-aabbccddeeff")
SEEDED_AGENCY_NAME = "Lumina Influence Agency"
RANDOM_SEED = 42


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _stable_uuid(slug: str) -> uuid.UUID:
    """UUID v5 determinístico — re-runs do seed produzem o mesmo ID."""
    return uuid.uuid5(SEED_NAMESPACE, slug)


def _load(name: str):
    with open(FIXTURES_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def _post_type_for_platform(plat: Platform, rng: random.Random) -> PostType:
    options = {
        Platform.INSTAGRAM: [PostType.IMAGE, PostType.REEL, PostType.CAROUSEL, PostType.VIDEO, PostType.STORY],
        Platform.TIKTOK: [PostType.VIDEO, PostType.SHORT],
        Platform.YOUTUBE: [PostType.VIDEO, PostType.SHORT],
    }
    return rng.choice(options[plat])


def _sentiment_label_from_score(score_0_100: float) -> SentimentLabel:
    if score_0_100 >= 70:
        return SentimentLabel.POSITIVE
    if score_0_100 >= 45:
        return SentimentLabel.NEUTRAL
    return SentimentLabel.NEGATIVE


COMMENT_TEMPLATES = {
    "positive": [
        "Excelente conteúdo, salvou meu dia!",
        "Já comprei, vale demais a pena.",
        "Aula incrível, parabéns pelo trabalho.",
        "Vocês são referência nesse nicho.",
        "Tô implementando isso amanhã.",
        "Conteúdo de altíssima qualidade.",
        "Compartilhei com a equipe inteira.",
        "Melhor review que vi sobre o tema.",
    ],
    "neutral": [
        "Interessante. Vou pesquisar mais.",
        "Tem alguma alternativa parecida?",
        "Funciona em outro modelo também?",
        "Vocês cobrem outras categorias?",
        "Aguardando comparativo.",
    ],
    "negative": [
        "Preço absurdo, não vale a pena.",
        "Já testei e não rendeu o esperado.",
        "Conteúdo muito promocional.",
        "Esperava mais profundidade.",
        "Parece propaganda disfarçada.",
    ],
}


KEY_PHRASES_POSITIVE = [
    "qualidade premium", "entrega rápida", "vale o investimento", "design impecável",
    "alta performance", "recomendo", "experiência fluida", "ótimo custo-benefício",
]
KEY_PHRASES_NEGATIVE = [
    "preço alto", "atendimento ruim", "garantia limitada", "espera longa",
]

RECOMMENDATION_TEMPLATES = [
    {"priority": "high", "title": "Aumentar peso do criador em campanhas premium",
     "description": "Métricas de coerência de marca e sentimento positivo justificam alocar +30% de budget."},
    {"priority": "medium", "title": "Usar este criador como benchmark do nicho",
     "description": "Score de ressonância está acima da média do segmento — referência pra outros."},
    {"priority": "low", "title": "Monitorar variação de bot probability em mídia paga",
     "description": "Boost de tráfego pago tende a elevar bot probability em 3-5%. Reanalisar 48h depois."},
    {"priority": "medium", "title": "Diversificar formato de hook em até 20%",
     "description": "Padrão de abertura repetitivo. Testar 2-3 hooks alternativos pra evitar fadiga."},
]


# --------------------------------------------------------------------------
# seed_clear
# --------------------------------------------------------------------------
def seed_clear() -> dict[str, int]:
    """Apaga todos os dados de domínio. Preserva alembic_version."""
    deleted: dict[str, int] = {}
    # Ordem reversa de dependência. Cascades cobrem grande parte; explícito por segurança.
    for model in [
        AIAnalysis,
        Comment,
        Post,
        CampaignInfluencer,
        Report,
        Campaign,
        SocialAccount,
        Influencer,
        ApiUsageLog,
        OAuthState,
        User,
        Agency,
        Plan,
    ]:
        count = db.session.query(model).count()
        if count:
            db.session.query(model).delete(synchronize_session=False)
            deleted[model.__tablename__] = count
    db.session.commit()
    return deleted


# --------------------------------------------------------------------------
# seed_run
# --------------------------------------------------------------------------
def seed_run() -> dict[str, int]:
    """Popula o banco. Aborta se a agência canônica já existir."""
    existing = db.session.scalar(select(Agency).where(Agency.name == SEEDED_AGENCY_NAME))
    if existing is not None:
        raise RuntimeError(
            "Seed já existe — rode 'flask seed clear' antes pra reseedar."
        )

    rng = random.Random(RANDOM_SEED)
    stats: dict[str, int] = {}

    # ---------- Plans ----------
    plans_by_name: dict[str, Plan] = {}
    for raw in _load("plans"):
        plan = Plan(
            id=_stable_uuid(f"plan:{raw['name']}"),
            name=raw["name"],
            max_influencers=raw["max_influencers"],
            max_analyses_per_month=raw["max_analyses_per_month"],
            allow_benchmarking=raw["allow_benchmarking"],
            price_brl_cents=raw["price_brl_cents"],
        )
        db.session.add(plan)
        plans_by_name[plan.name] = plan
    db.session.flush()
    stats["plans"] = len(plans_by_name)

    # ---------- Agency ----------
    agency_raw = _load("agency")
    agency = Agency(
        id=_stable_uuid("agency:lumina"),
        name=agency_raw["name"],
        cnpj=agency_raw["cnpj"],
        plan=plans_by_name[agency_raw["plan_name"]],
    )
    db.session.add(agency)
    db.session.flush()
    stats["agencies"] = 1

    # ---------- Users ----------
    users_by_slug: dict[str, User] = {}
    for raw in _load("users"):
        u = User(
            id=_stable_uuid(f"user:{raw['slug']}"),
            email=raw["email"],
            name=raw["name"],
            avatar_url=None,
            oauth_provider=OAuthProvider(raw["oauth_provider"]),
            oauth_id=f"seed-{raw['oauth_provider']}-{raw['slug']}",
            role=UserRole(raw["role"]),
            agency=agency,
        )
        db.session.add(u)
        users_by_slug[raw["slug"]] = u
    db.session.flush()
    stats["users"] = len(users_by_slug)

    # ---------- Influencers + SocialAccounts ----------
    influencers_by_slug: dict[str, Influencer] = {}
    social_accounts_by_inf: dict[str, list[SocialAccount]] = {}
    inf_data_by_slug: dict[str, dict] = {}

    for raw in _load("influencers"):
        inf = Influencer(
            id=_stable_uuid(f"influencer:{raw['slug']}"),
            agency=agency,
            display_name=raw["display_name"],
            niche=raw["niche"],
            bio=raw["bio"],
            status=InfluencerStatus.ACTIVE,
        )
        db.session.add(inf)
        influencers_by_slug[raw["slug"]] = inf
        inf_data_by_slug[raw["slug"]] = raw

        accounts: list[SocialAccount] = []
        for plat_str in raw["platforms"]:
            plat = Platform(plat_str)
            # Distribuir followers entre plataformas (1ª recebe ~60%, demais dividem o resto)
            n_plat = len(raw["platforms"])
            if n_plat == 1:
                follower_share = raw["followers"]
            elif plat_str == raw["platforms"][0]:
                follower_share = int(raw["followers"] * 0.6)
            else:
                follower_share = int(raw["followers"] * 0.4 / (n_plat - 1))

            sa = SocialAccount(
                id=_stable_uuid(f"sa:{raw['slug']}:{plat_str}"),
                influencer=inf,
                platform=plat,
                handle=raw["handle"],
                platform_user_id=f"{plat_str}-{raw['slug']}",
                follower_count=follower_share,
                token_expires_at=None,
                last_synced_at=datetime.now(timezone.utc) - timedelta(hours=rng.randint(1, 48)),
            )
            db.session.add(sa)
            accounts.append(sa)
        social_accounts_by_inf[raw["slug"]] = accounts
    db.session.flush()
    stats["influencers"] = len(influencers_by_slug)
    stats["social_accounts"] = sum(len(v) for v in social_accounts_by_inf.values())

    # ---------- Campaigns + CampaignInfluencer ----------
    campaigns_by_slug: dict[str, Campaign] = {}
    n_links = 0
    for raw in _load("campaigns"):
        camp = Campaign(
            id=_stable_uuid(f"campaign:{raw['slug']}"),
            agency=agency,
            brand_name=raw["brand_name"],
            title=raw["title"],
            period_start=date.fromisoformat(raw["period_start"]),
            period_end=date.fromisoformat(raw["period_end"]),
            budget_brl_cents=raw["budget_brl_cents"],
            status=CampaignStatus(raw["status"]),
        )
        db.session.add(camp)
        campaigns_by_slug[raw["slug"]] = camp

        for p in raw["participations"]:
            link = CampaignInfluencer(
                id=_stable_uuid(f"ci:{raw['slug']}:{p['influencer_slug']}"),
                campaign=camp,
                influencer=influencers_by_slug[p["influencer_slug"]],
                fee_brl_cents=p["fee_brl_cents"],
                deliverables=p["deliverables"],
            )
            db.session.add(link)
            n_links += 1
    db.session.flush()
    stats["campaigns"] = len(campaigns_by_slug)
    stats["campaign_influencers"] = n_links

    # ---------- Posts (procedural) ----------
    posts: list[Post] = []
    now = datetime.now(timezone.utc)
    window_days = 90

    for slug, inf in influencers_by_slug.items():
        data = inf_data_by_slug[slug]
        n_posts = rng.randint(10, 17)  # média ≈ 13 → ~195 total
        accounts = social_accounts_by_inf[slug]

        # Quais campanhas o influencer participa
        inf_campaigns = [
            campaigns_by_slug[c_raw["slug"]]
            for c_raw in _load("campaigns")
            if any(p["influencer_slug"] == slug for p in c_raw["participations"])
            and CampaignStatus(c_raw["status"]) in (CampaignStatus.ACTIVE, CampaignStatus.ENDED)
        ]

        for i in range(n_posts):
            sa = rng.choice(accounts)
            posted_at = now - timedelta(
                days=rng.randint(0, window_days - 1),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59),
            )

            # ~40% dos posts são de campanha
            campaign = rng.choice(inf_campaigns) if (inf_campaigns and rng.random() < 0.4) else None

            base_reach = int(sa.follower_count * (data["engagement"] / 100) * rng.uniform(0.6, 1.6))
            reach_total = max(100, base_reach)
            reach_organic = int(reach_total * data["organic_reach_pct"] / 100)
            reach_paid = reach_total - reach_organic
            impressions = int(reach_total * rng.uniform(1.2, 2.0))
            likes = int(reach_total * (data["engagement"] / 100) * rng.uniform(0.4, 1.2))
            comments_count = int(likes * rng.uniform(0.04, 0.15))
            shares = int(likes * rng.uniform(0.05, 0.18))
            saves = int(likes * rng.uniform(0.10, 0.25))

            post_type = _post_type_for_platform(sa.platform, rng)
            avg_watch = None
            retention = None
            if post_type in (PostType.VIDEO, PostType.REEL, PostType.SHORT, PostType.STORY):
                avg_watch = round(rng.uniform(8.0, 42.0), 1)
                retention = round(rng.uniform(0.35, 0.85), 3)

            post = Post(
                id=uuid.uuid4(),
                social_account=sa,
                campaign=campaign,
                platform_post_id=f"{sa.platform.value}-{slug}-{i:03d}",
                post_type=post_type,
                posted_at=posted_at,
                caption=f"Post #{i + 1} de {data['display_name']} — {data['niche']}.",
                video_url=f"https://cdn.lumina.example/{slug}/{i}.mp4" if avg_watch else None,
                thumbnail_url=f"https://cdn.lumina.example/{slug}/{i}-thumb.jpg",
                reach_total=reach_total,
                reach_organic=reach_organic,
                reach_paid=reach_paid,
                impressions=impressions,
                likes=likes,
                comments_count=comments_count,
                shares=shares,
                saves=saves,
                avg_watch_time=avg_watch,
                retention_rate=retention,
            )
            db.session.add(post)
            posts.append(post)

    db.session.flush()
    stats["posts"] = len(posts)

    # ---------- Comments (~15 por post) ----------
    n_comments = 0
    for post in posts:
        n_c = rng.randint(12, 18)
        # Distribuição baseada no sentiment do influencer dono
        data = inf_data_by_slug[
            next(s for s, sa_list in social_accounts_by_inf.items()
                 if any(sa.id == post.social_account_id for sa in sa_list))
        ]
        sent = data["sentiment_score"]
        pos_weight = max(0.1, sent / 100)
        neg_weight = max(0.05, (100 - sent) / 200)
        neu_weight = 1 - pos_weight - neg_weight

        for c in range(n_c):
            r = rng.random()
            if r < pos_weight:
                bucket = "positive"
            elif r < pos_weight + neu_weight:
                bucket = "neutral"
            else:
                bucket = "negative"
            content = rng.choice(COMMENT_TEMPLATES[bucket])
            comment = Comment(
                id=uuid.uuid4(),
                post=post,
                platform_comment_id=f"cmt-{post.platform_post_id}-{c:02d}",
                content=content,
                author_handle=f"user{rng.randint(1000, 9999)}",
                posted_at=post.posted_at + timedelta(hours=rng.randint(1, 72)),
                like_count=rng.randint(0, 200),
            )
            db.session.add(comment)
            n_comments += 1
    db.session.flush()
    stats["comments"] = n_comments

    # ---------- AI Analyses (75% dos posts) ----------
    # Os 25% restantes ficam marcados needs_analysis=True (trabalho pro job B7).
    n_analyses = 0
    for post in posts:
        if rng.random() >= 0.75:
            post.needs_analysis = True
            continue
        data = inf_data_by_slug[
            next(s for s, sa_list in social_accounts_by_inf.items()
                 if any(sa.id == post.social_account_id for sa in sa_list))
        ]
        sent_score_normalized = round((data["sentiment_score"] / 100) * 2 - 1, 3)  # -1..1
        sent_label = _sentiment_label_from_score(data["sentiment_score"])

        # Sentiment breakdown — soma 100
        tech = rng.randint(30, 50)
        purchase = rng.randint(20, 35)
        skepticism = rng.randint(5, 18)
        neutral = max(0, 100 - tech - purchase - skepticism)

        n_pos_phrases = rng.randint(3, 6)
        n_neg_phrases = rng.randint(0, 2)
        key_phrases = (
            rng.sample(KEY_PHRASES_POSITIVE, k=min(n_pos_phrases, len(KEY_PHRASES_POSITIVE)))
            + rng.sample(KEY_PHRASES_NEGATIVE, k=min(n_neg_phrases, len(KEY_PHRASES_NEGATIVE)))
        )
        recs = rng.sample(RECOMMENDATION_TEMPLATES, k=rng.randint(2, 3))

        analysis = AIAnalysis(
            id=uuid.uuid4(),
            post=post,
            analyzed_at=post.posted_at + timedelta(hours=rng.randint(2, 48)),
            model_version="seed-fixture-v1",
            sentiment_score=sent_score_normalized,
            sentiment_label=sent_label,
            script_score=round(rng.uniform(5.0, 9.5), 2),
            brand_coherence_score=round(data["brand_coherence"] + rng.uniform(-5, 3), 2),
            bot_probability=round(data["bot_probability"] + rng.uniform(-2, 4), 2),
            # Faixa suspeita como grandeza própria, e não fração da de bot: no
            # dado real ela vem medida pelo modelo, e o seed precisa ter a
            # mesma forma para a tela de demonstração exercitar o mesmo
            # caminho. Fica um pouco acima da de bot porque dúvida é mais
            # comum que automação confirmada.
            suspicious_probability=round(
                data["bot_probability"] * rng.uniform(1.1, 1.8), 2
            ),
            transcript_text=(
                "Olha só esse drop — testei por semanas e a diferença é absurda. "
                "Pra quem trabalha pesado, vale cada centavo. Link na bio com cupom."
                if post.post_type in (PostType.VIDEO, PostType.REEL, PostType.SHORT)
                else None
            ),
            key_phrases=key_phrases,
            recommendations=recs,
            sentiment_breakdown={
                "technical_enthusiasm": tech,
                "purchase_intent": purchase,
                "value_skepticism": skepticism,
                "neutral": neutral,
            },
            raw_response={"seed": True, "version": "v1"},
        )
        db.session.add(analysis)
        n_analyses += 1
    db.session.flush()
    stats["ai_analyses"] = n_analyses
    stats["posts_needing_analysis"] = sum(1 for p in posts if p.needs_analysis)

    # ---------- Reports ----------
    n_reports = 0
    for raw in _load("reports"):
        rpt = Report(
            id=_stable_uuid(f"report:{raw['slug']}"),
            agency=agency,
            campaign=campaigns_by_slug.get(raw["campaign_slug"]),
            generated_by=users_by_slug.get(raw["generated_by_slug"]),
            title=raw["title"],
            period_start=date.fromisoformat(raw["period_start"]),
            period_end=date.fromisoformat(raw["period_end"]),
            format=ReportFormat(raw["format"]),
            sections=raw["sections"],
            pdf_url=None,
            generated_at=datetime.fromisoformat(raw["generated_at_iso"].replace("Z", "+00:00")),
        )
        db.session.add(rpt)
        n_reports += 1
    stats["reports"] = n_reports

    db.session.commit()
    logger.info("Seed concluído: %s", stats)
    return stats


def _format_stats(stats: Iterable[tuple[str, int]]) -> str:
    return ", ".join(f"{k}={v}" for k, v in stats)
