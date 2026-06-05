"""Job: processa posts marcados como needs_analysis via Gemini, em lotes.

Lote pequeno por execução pra controlar custo/quota. Cada análise bem-sucedida
desmarca o post. Erros de quota interrompem o lote (tenta de novo na próxima rodada).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.extensions import db, scheduler
from src.integrations.gemini import GeminiClient, GeminiNotConfiguredError, GeminiQuotaError
from src.models import Influencer, Post, SocialAccount
from src.services.ai_analysis_service import analyze_post
from src.utils.errors import LuminaError

logger = logging.getLogger("lumina.jobs.run_pending_analyses")

DEFAULT_BATCH = 5


def run_pending_analyses(*, limit: int = DEFAULT_BATCH, client: GeminiClient | None = None) -> dict:
    """Lógica do job (assume app context ativo)."""
    posts = list(
        db.session.scalars(
            select(Post).where(Post.needs_analysis.is_(True)).limit(limit)
        ).all()
    )
    if not posts:
        logger.info("run_pending_analyses: nada pendente")
        return {"analyzed": 0, "pending_before": 0}

    # Instancia o client uma vez (a menos que injetado nos testes).
    if client is None:
        try:
            client = GeminiClient()
        except GeminiNotConfiguredError:
            logger.warning("run_pending_analyses: GEMINI_API_KEY ausente — pulando lote")
            return {"analyzed": 0, "skipped": "gemini_not_configured", "pending_before": len(posts)}

    analyzed = 0
    for post in posts:
        agency_id = _agency_of_post(post)
        try:
            analyze_post(post, agency_id=agency_id, client=client)
            post.needs_analysis = False
            db.session.commit()
            analyzed += 1
        except GeminiQuotaError:
            logger.warning("run_pending_analyses: cota Gemini excedida — interrompendo lote")
            db.session.rollback()
            break
        except LuminaError as exc:
            logger.error("run_pending_analyses: falha no post %s: %s", post.id, exc.code)
            db.session.rollback()

    logger.info("run_pending_analyses: %d posts analisados", analyzed)
    return {"analyzed": analyzed, "batch": len(posts)}


def _agency_of_post(post: Post):
    sa = db.session.get(SocialAccount, post.social_account_id)
    inf = db.session.get(Influencer, sa.influencer_id)
    return inf.agency_id


def run_pending_analyses_job() -> None:
    """Entrypoint chamado pelo APScheduler (cria app context)."""
    with scheduler.app.app_context():
        try:
            run_pending_analyses()
        except Exception:
            logger.exception("run_pending_analyses falhou")
            db.session.rollback()
