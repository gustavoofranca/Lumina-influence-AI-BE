"""Schemas de Campaign."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from src.models import CampaignStatus
from src.schemas.campos import (
    Centavos,
    DataDeNegocio,
    LinhaOpcional,
    Nome,
    TextoOpcional,
    periodo_em_ordem,
)


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
    fee_brl_cents: Centavos = 0
    deliverables: TextoOpcional(500) = None


class CampaignCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: Nome(160)
    title: LinhaOpcional(200) = None
    period_start: DataDeNegocio
    period_end: DataDeNegocio
    budget_brl_cents: Centavos = 0
    status: CampaignStatus = CampaignStatus.DRAFT
    participants: list[CampaignParticipantIn] = Field(default_factory=list)

    # No campo do fim, e não no modelo: assim o erro aponta `period_end` e a tela
    # sabe onde mostrá-lo.
    @field_validator("period_end")
    @classmethod
    def _fim_depois_do_inicio(cls, fim: date, info: ValidationInfo) -> date:
        periodo_em_ordem(info.data.get("period_start"), fim)
        return fim

    @model_validator(mode="after")
    def _check_participants(self):
        ids = [p.influencer_id for p in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("o mesmo criador aparece mais de uma vez")
        return self


class CampaignUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Campo obrigatório no banco não é `Optional` aqui. O `None` padrão só marca
    # "não enviado" — a rota aplica `exclude_unset` —, e um `null` explícito vira
    # erro de validação no próprio campo, em vez de erro 500 no banco.
    brand_name: Nome(160) = None
    title: LinhaOpcional(200) = None
    period_start: DataDeNegocio = None
    period_end: DataDeNegocio = None
    budget_brl_cents: Centavos = None
    status: CampaignStatus = None
