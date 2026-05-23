"""Healthcheck — testa conectividade real com o banco."""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.extensions import db

logger = logging.getLogger(__name__)

bp = Blueprint("health", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    db_status = "connected"
    http_status = 200
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("healthcheck: db indisponível: %s", exc.__class__.__name__)
        db_status = "disconnected"
        http_status = 503

    payload = {
        "status": "ok" if http_status == 200 else "degraded",
        "db": db_status,
        "version": current_app.config.get("VERSION", "0.0.0"),
        "env": current_app.config.get("ENV", "unknown"),
    }
    return jsonify(payload), http_status
