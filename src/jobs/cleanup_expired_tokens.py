"""Job: limpeza diária de OAuthStates expirados."""
from __future__ import annotations

import logging

from src.extensions import db, scheduler
from src.services.auth_service import cleanup_expired_oauth_states

logger = logging.getLogger("lumina.jobs.cleanup_expired_tokens")


def run_cleanup_expired_tokens() -> dict:
    """Lógica do job (assume app context ativo)."""
    removed = cleanup_expired_oauth_states()
    logger.info("cleanup_expired_tokens: %d oauth_states removidos", removed)
    return {"removed": removed}


def cleanup_expired_tokens_job() -> None:
    """Entrypoint chamado pelo APScheduler (cria app context)."""
    with scheduler.app.app_context():
        try:
            run_cleanup_expired_tokens()
        except Exception:
            logger.exception("cleanup_expired_tokens falhou")
            db.session.rollback()
