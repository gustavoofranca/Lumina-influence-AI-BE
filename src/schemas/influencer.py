"""Schemas de Influencer (inclui contas sociais aninhadas + agregados)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import InfluencerStatus
from src.schemas.social_account import SocialAccountOut


class InfluencerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agency_id: uuid.UUID
    display_name: str
    niche: Optional[str] = None
    bio: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    social_accounts: list[SocialAccountOut] = []
    # Agregados convenientes pro front (derivados das contas sociais)
    total_followers: int = 0
    platforms: list[str] = []

    @model_validator(mode="after")
    def _compute_aggregates(self):
        if self.social_accounts:
            self.total_followers = sum(sa.follower_count for sa in self.social_accounts)
            self.platforms = sorted({sa.platform for sa in self.social_accounts})
        return self


class InfluencerCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    niche: Optional[str] = Field(default=None, max_length=80)
    bio: Optional[str] = Field(default=None, max_length=500)
    status: InfluencerStatus = InfluencerStatus.ACTIVE


class InfluencerUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    niche: Optional[str] = Field(default=None, max_length=80)
    bio: Optional[str] = Field(default=None, max_length=500)
    status: Optional[InfluencerStatus] = None
