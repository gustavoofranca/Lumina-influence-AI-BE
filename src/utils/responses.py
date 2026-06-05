"""Helpers para o envelope padrão de resposta `{ data, meta }`."""
from __future__ import annotations

from typing import Any

from flask import jsonify


def ok(data: Any, *, meta: dict | None = None, status: int = 200):
    body: dict[str, Any] = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status


def created(data: Any):
    return ok(data, status=201)


def no_content():
    return "", 204


def paginated(items: list, pagination) -> tuple:
    """Resposta de listagem com meta.pagination."""
    from src.utils.pagination import pagination_meta

    return ok(items, meta=pagination_meta(pagination))
