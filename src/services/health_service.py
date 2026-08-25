"""Verificação de dependências externas para o healthcheck."""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.extensions import db

logger = logging.getLogger(__name__)


def database_connected() -> bool:
    """Toca o banco de verdade — um ping que não abre conexão não prova nada."""
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("healthcheck: db indisponível: %s", exc.__class__.__name__)
        return False
