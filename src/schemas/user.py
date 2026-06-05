"""Schemas de User (gestão de membros da agência)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.models import OAuthProvider, UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    oauth_provider: str
    role: str
    agency_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class UserCreateIn(BaseModel):
    """Criação de membro (convite). Sem senha — login é só OAuth."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = Field(min_length=1, max_length=160)
    role: UserRole = UserRole.MEMBER
    oauth_provider: OAuthProvider = OAuthProvider.GOOGLE


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    role: Optional[UserRole] = None
    avatar_url: Optional[str] = Field(default=None, max_length=500)
