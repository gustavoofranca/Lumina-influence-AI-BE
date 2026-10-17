"""Schemas de Agency."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.schemas.campos import Cnpj, NomeDeEmpresa
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

    # Campo obrigatório no banco não é `Optional` aqui. O `None` padrão só marca
    # "não enviado" — a rota aplica `exclude_unset` —, e um `null` explícito vira
    # erro de validação no próprio campo, em vez de erro 500 no banco.
    name: NomeDeEmpresa(160) = None
    # Formato aqui; dígito verificador no serviço, só quando o CNPJ muda.
    cnpj: Cnpj = None
    plan_id: Optional[uuid.UUID] = None
