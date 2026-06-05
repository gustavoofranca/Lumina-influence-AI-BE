"""Schemas de SocialAccount. NUNCA expõe tokens criptografados."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models import Platform


class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    influencer_id: uuid.UUID
    platform: str
    handle: str
    platform_user_id: Optional[str] = None
    follower_count: int
    token_expires_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Campos *_encrypted deliberadamente omitidos.


class SocialAccountCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    influencer_id: uuid.UUID
    platform: Platform
    handle: str = Field(min_length=1, max_length=120)
    platform_user_id: Optional[str] = Field(default=None, max_length=120)
    follower_count: int = Field(default=0, ge=0)


class SocialAccountUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: Optional[str] = Field(default=None, min_length=1, max_length=120)
    platform_user_id: Optional[str] = Field(default=None, max_length=120)
    follower_count: Optional[int] = Field(default=None, ge=0)
