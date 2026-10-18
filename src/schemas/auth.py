"""Pydantic schemas usados nos endpoints de /auth."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    """Representação pública de um usuário autenticado. Nunca inclui o hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    oauth_provider: Optional[str] = None
    role: str
    agency_id: Optional[uuid.UUID] = None
    has_password: bool = False
    email_verified: bool = False
    terms_accepted: bool = False
    created_at: datetime


class AgencySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # O front usa para levar o admin sem CNPJ ao primeiro acesso.
    cnpj: Optional[str] = None


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int = Field(..., description="TTL do access token")


class LoginCallbackOut(BaseModel):
    """Resposta do /auth/<provider>/callback."""

    user: UserOut
    agency: Optional[AgencySummaryOut] = None
    tokens: TokenPairOut


class MeOut(BaseModel):
    user: UserOut
    agency: Optional[AgencySummaryOut] = None
