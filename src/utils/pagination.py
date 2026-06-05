"""Paginação padronizada usando o helper do Flask-SQLAlchemy."""
from __future__ import annotations

from flask import request

from src.extensions import db

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


def get_pagination_args() -> tuple[int, int]:
    """Lê `page` e `per_page` da query string com limites sãos."""
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", DEFAULT_PER_PAGE, type=int) or DEFAULT_PER_PAGE
    page = max(page, 1)
    per_page = min(max(per_page, 1), MAX_PER_PAGE)
    return page, per_page


def paginate(select_stmt):
    """Aplica paginação a um `select()` 2.0. Retorna o objeto Pagination do FSA."""
    page, per_page = get_pagination_args()
    return db.paginate(select_stmt, page=page, per_page=per_page, error_out=False)


def pagination_meta(pagination) -> dict:
    """Constrói o bloco meta.pagination a partir do objeto Pagination."""
    return {
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    }
