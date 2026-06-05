"""Schemas de Plan (somente leitura nesta fase)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    max_influencers: int
    max_analyses_per_month: int
    allow_benchmarking: bool
    price_brl_cents: int
