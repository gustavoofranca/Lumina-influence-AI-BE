"""Schemas de User (gestão de membros da agência)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr

from src.models import OAuthProvider, UserRole
from src.schemas.campos import NomeDePessoa, UrlHttpsOpcional


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    oauth_provider: str
    role: str
    agency_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class UserCreateIn(BaseModel):
    """Criação de membro (convite). Sem senha — login é só OAuth."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: NomeDePessoa(160)
    role: UserRole = UserRole.MEMBER
    oauth_provider: OAuthProvider = OAuthProvider.GOOGLE


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Campo obrigatório no banco não é `Optional` aqui. O `None` padrão só marca
    # "não enviado" — a rota aplica `exclude_unset` —, e um `null` explícito vira
    # erro de validação no próprio campo, em vez de erro 500 no banco.
    name: NomeDePessoa(160) = None
    role: UserRole = None
    avatar_url: UrlHttpsOpcional = None
