"""Emissão e verificação de JWTs.

Convenções:
- Access token: `type=access`, TTL curto (Config.JWT_ACCESS_TTL).
- Refresh token: `type=refresh`, TTL longo (Config.JWT_REFRESH_TTL).
- Algoritmo HS256 (chave simétrica em Config.JWT_SECRET).
- Cada token tem `jti` único pra rastreamento futuro.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from flask import current_app

from src.utils.errors import UnauthorizedError

ALGO = "HS256"
TokenType = Literal["access", "refresh"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret() -> str:
    return current_app.config["JWT_SECRET"]


def _ttl(token_type: TokenType) -> timedelta:
    key = "JWT_ACCESS_TTL" if token_type == "access" else "JWT_REFRESH_TTL"
    return current_app.config[key]


def encode_token(
    *,
    token_type: TokenType,
    user_id: str,
    agency_id: str | None = None,
    role: str | None = None,
    email: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Emite um JWT (access ou refresh) pra um usuário."""
    iat = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": int(iat.timestamp()),
        "exp": int((iat + _ttl(token_type)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if token_type == "access":
        # Claims de autorização ficam só no access — refresh é minimal.
        if agency_id is not None:
            payload["agency_id"] = str(agency_id)
        if role is not None:
            payload["role"] = role
        if email is not None:
            payload["email"] = email
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=ALGO)


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decodifica e valida assinatura, expiração e tipo. Levanta UnauthorizedError."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGO])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token expirado", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token inválido", code="token_invalid") from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedError(
            f"Token do tipo errado (esperado {expected_type})",
            code="token_wrong_type",
        )
    return payload


def issue_token_pair(user) -> dict[str, str]:
    """Atalho — emite access + refresh pra um User."""
    access = encode_token(
        token_type="access",
        user_id=user.id,
        agency_id=user.agency_id,
        role=user.role.value if user.role else None,
        email=user.email,
    )
    refresh = encode_token(token_type="refresh", user_id=user.id)
    return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer"}
