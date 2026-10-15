"""Schemas de Report."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from src.schemas.campos import DataDeNegocio, Linha, periodo_em_ordem
from src.services.report_service import SECTION_KEYS


class ReportCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: uuid.UUID
    title: Linha(200)
    period_start: DataDeNegocio
    period_end: DataDeNegocio
    # Omitir o campo continua valendo "todas as seções". Uma lista vazia
    # explícita não: gerava, sem avisar, o relatório completo para quem não
    # marcou nada — a tela já exige pelo menos uma.
    sections: list[str] = Field(default_factory=lambda: list(SECTION_KEYS))

    @field_validator("period_end")
    @classmethod
    def _fim_depois_do_inicio(cls, fim: date, info: ValidationInfo) -> date:
        periodo_em_ordem(info.data.get("period_start"), fim)
        return fim

    @field_validator("sections")
    @classmethod
    def _valid_sections(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("escolha pelo menos uma seção")
        invalid = [s for s in v if s not in SECTION_KEYS]
        if invalid:
            raise ValueError(f"seções inválidas: {', '.join(map(str, invalid))}")
        if len(set(v)) != len(v):
            raise ValueError("a mesma seção aparece mais de uma vez")
        return v


class ReportPreviewIn(ReportCreateIn):
    """Mesma entrada da criação — a pré-visualização não grava nada."""

    title: Linha(200) = "Prévia"


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
