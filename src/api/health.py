"""Healthcheck — testa conectividade real com o banco."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from src.services import health_service

bp = Blueprint("health", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    connected = health_service.database_connected()
    http_status = 200 if connected else 503

    payload = {
        "status": "ok" if connected else "degraded",
        "db": "connected" if connected else "disconnected",
        "version": current_app.config.get("VERSION", "0.0.0"),
        "env": current_app.config.get("ENV", "unknown"),
    }
    return jsonify(payload), http_status
