"""Decorator @require_auth — injeta g.current_user a partir do Bearer token."""
from __future__ import annotations

import uuid
from functools import wraps
from typing import Callable

from flask import g, request
from sqlalchemy import select

from src.extensions import db
from src.models import User
from src.utils.errors import UnauthorizedError
from src.utils.jwt_utils import decode_token


def _extract_bearer() -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise UnauthorizedError(
            "Header Authorization ausente ou mal-formado",
            code="missing_bearer",
        )
    return auth.removeprefix("Bearer ").strip()


def _load_user(user_id_str: str) -> User:
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise UnauthorizedError("Claim sub inválido", code="invalid_sub") from exc

    user = db.session.scalar(select(User).where(User.id == user_id))
    if user is None or user.deleted_at is not None:
        raise UnauthorizedError("Usuário não encontrado", code="user_not_found")
    return user


def require_auth(view: Callable) -> Callable:
    """Exige Authorization: Bearer <access_token>. Injeta g.current_user."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer()
        payload = decode_token(token, expected_type="access")
        user = _load_user(payload["sub"])
        g.current_user = user
        g.jwt_claims = payload
        return view(*args, **kwargs)

    return wrapper


def require_refresh(view: Callable) -> Callable:
    """Variante que aceita refresh token (pra /auth/refresh)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer()
        payload = decode_token(token, expected_type="refresh")
        user = _load_user(payload["sub"])
        g.current_user = user
        g.jwt_claims = payload
        return view(*args, **kwargs)

    return wrapper
