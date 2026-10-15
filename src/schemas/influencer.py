"""Schemas de Influencer (inclui contas sociais aninhadas + agregados)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from src.models import InfluencerStatus
from src.schemas.campos import Nome, NomeOpcional, TextoOpcional
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

    display_name: Nome(160)
    niche: NomeOpcional(80) = None
    bio: TextoOpcional(500) = None
    status: InfluencerStatus = InfluencerStatus.ACTIVE


class InfluencerUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Campo obrigatório no banco não é `Optional` aqui. O `None` padrão só marca
    # "não enviado" — a rota aplica `exclude_unset` —, e um `null` explícito vira
    # erro de validação no próprio campo, em vez de erro 500 no banco.
    display_name: Nome(160) = None
    niche: NomeOpcional(80) = None
    bio: TextoOpcional(500) = None
    status: InfluencerStatus = None
