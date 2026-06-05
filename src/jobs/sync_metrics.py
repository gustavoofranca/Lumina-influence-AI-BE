"""Job: sincronização de métricas dos posts recentes.

Nesta fase (pré-B8) simula a coleta — aplica crescimento modesto às métricas dos
posts dos últimos 7 dias e atualiza `last_synced_at` das contas. Na B8, o corpo
de `run_sync_metrics` será substituído por chamadas reais às APIs sociais.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.extensions import db, scheduler
from src.models import Post, SocialAccount

logger = logging.getLogger("lumina.jobs.sync_metrics")

RECENT_DAYS = 7


def run_sync_metrics(*, rng: random.Random | None = None) -> dict:
    """Lógica do job (assume app context ativo)."""
    rng = rng or random.Random()
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)

    posts = list(db.session.scalars(select(Post)).all())
    recent = [p for p in posts if _as_aware(p.posted_at) >= since]

    updated = 0
    synced_accounts: set = set()
    for p in posts:
        if p not in recent:
            continue
        # Crescimento simulado: 0.5% a 4% nas métricas de engajamento/alcance.
        growth = 1 + rng.uniform(0.005, 0.04)
        p.likes = int(p.likes * growth)
        p.comments_count = int(p.comments_count * growth)
        p.shares = int(p.shares * growth)
        p.saves = int(p.saves * growth)
        p.reach_organic = int(p.reach_organic * growth)
        p.reach_paid = int(p.reach_paid * growth)
        p.reach_total = p.reach_organic + p.reach_paid
        p.impressions = int(p.impressions * growth)
        synced_accounts.add(p.social_account_id)
        updated += 1

    now = datetime.now(timezone.utc)
    for sa in db.session.scalars(
        select(SocialAccount).where(SocialAccount.id.in_(synced_accounts))
    ).all() if synced_accounts else []:
        sa.last_synced_at = now

    db.session.commit()
    logger.info(
        "sync_metrics: %d posts atualizados, %d contas sincronizadas",
        updated, len(synced_accounts),
    )
    return {"posts_updated": updated, "accounts_synced": len(synced_accounts)}


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def sync_metrics_job() -> None:
    """Entrypoint chamado pelo APScheduler (cria app context)."""
    with scheduler.app.app_context():
        try:
            run_sync_metrics()
        except Exception:
            logger.exception("sync_metrics falhou")
            db.session.rollback()
