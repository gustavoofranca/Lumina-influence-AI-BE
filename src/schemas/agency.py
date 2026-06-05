"""Schemas de Agency."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.plan import PlanOut


class AgencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cnpj: Optional[str] = None
    plan_id: Optional[uuid.UUID] = None
    plan: Optional[PlanOut] = None
    created_at: datetime
    updated_at: datetime


class AgencyUpdateIn(BaseModel):
    """PATCH parcial — todos os campos opcionais."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    cnpj: Optional[str] = Field(default=None, max_length=18)
    plan_id: Optional[uuid.UUID] = None
