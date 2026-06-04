"""Pydantic schemas usados nos endpoints de /auth."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    """Representação pública de um usuário autenticado."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    oauth_provider: str
    role: str
    agency_id: Optional[uuid.UUID] = None
    created_at: datetime


class AgencySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


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
