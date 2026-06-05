"""Autorização: escopo por agência + checagem de role.

Todos os helpers assumem que `@require_auth` já rodou e populou g.current_user.
"""
from __future__ import annotations

import uuid
from functools import wraps
from typing import Callable

from flask import g
from sqlalchemy import select

from src.extensions import db
from src.models import UserRole
from src.utils.errors import ForbiddenError, NotFoundError


def current_agency_id() -> uuid.UUID:
    """ID da agência do usuário logado. 403 se ele não tiver agência."""
    user = g.current_user
    if user.agency_id is None:
        raise ForbiddenError("Usuário sem agência associada", code="no_agency")
    return user.agency_id


def require_role(*allowed: UserRole) -> Callable:
    """Decorator: exige que g.current_user.role esteja em `allowed`."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.current_user.role not in allowed:
                raise ForbiddenError(
                    "Permissão insuficiente para esta ação",
                    code="insufficient_role",
                    details={"required": [r.value for r in allowed]},
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def get_scoped_or_404(model, obj_id, *, agency_attr: str = "agency_id"):
    """Busca por id E pela agência do usuário. 404 se não existir/for de outra agência.

    Retornar 404 (não 403) evita vazar a existência de recursos de outras agências.
    Ignora registros soft-deleted (deleted_at).
    """
    try:
        parsed_id = obj_id if isinstance(obj_id, uuid.UUID) else uuid.UUID(str(obj_id))
    except (ValueError, AttributeError):
        raise NotFoundError(f"{model.__name__} não encontrado", code="not_found")

    stmt = select(model).where(
        model.id == parsed_id,
        getattr(model, agency_attr) == current_agency_id(),
    )
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))

    obj = db.session.scalar(stmt)
    if obj is None:
        raise NotFoundError(f"{model.__name__} não encontrado", code="not_found")
    return obj
