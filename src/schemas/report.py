"""Schemas de Report."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.services.report_service import SECTION_KEYS


class ReportCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    sections: list[str] = Field(default_factory=lambda: list(SECTION_KEYS))

    @field_validator("sections")
    @classmethod
    def _valid_sections(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in SECTION_KEYS]
        if invalid:
            raise ValueError(f"Seções inválidas: {invalid}. Válidas: {SECTION_KEYS}")
        return v or list(SECTION_KEYS)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agency_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    generated_by_user_id: Optional[uuid.UUID] = None
    title: str
    period_start: date
    period_end: date
    format: str
    sections: Optional[dict] = None
    pdf_url: Optional[str] = None
    generated_at: datetime
