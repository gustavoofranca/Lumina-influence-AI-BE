"""Schemas de Campaign."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import CampaignStatus


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agency_id: uuid.UUID
    brand_name: str
    title: Optional[str] = None
    period_start: date
    period_end: date
    budget_brl_cents: int
    status: str
    created_at: datetime
    updated_at: datetime


class CampaignParticipantIn(BaseModel):
    """Vínculo de um influencer com a campanha, com o cachê contratado."""

    model_config = ConfigDict(extra="forbid")

    influencer_id: uuid.UUID
    fee_brl_cents: int = Field(default=0, ge=0)
    deliverables: Optional[str] = Field(default=None, max_length=500)


class CampaignCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str = Field(min_length=1, max_length=160)
    title: Optional[str] = Field(default=None, max_length=200)
    period_start: date
    period_end: date
    budget_brl_cents: int = Field(default=0, ge=0)
    status: CampaignStatus = CampaignStatus.DRAFT
    participants: list[CampaignParticipantIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end não pode ser anterior a period_start")
        return self

    @model_validator(mode="after")
    def _check_participants(self):
        ids = [p.influencer_id for p in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("participants repete o mesmo influencer_id")
        return self


class CampaignUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    title: Optional[str] = Field(default=None, max_length=200)
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    budget_brl_cents: Optional[int] = Field(default=None, ge=0)
    status: Optional[CampaignStatus] = None
