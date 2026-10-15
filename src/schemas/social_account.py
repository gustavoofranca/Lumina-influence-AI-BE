"""Schemas de SocialAccount. NUNCA expõe tokens criptografados."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.models import Platform
from src.schemas.campos import Handle, IdDePlataforma, Seguidores


class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    influencer_id: uuid.UUID
    platform: str
    handle: str
    platform_user_id: Optional[str] = None
    follower_count: int
    token_expires_at: Optional[datetime] = None
    # Deriva da presença do token, não da existência da conta: a conta sobrevive
    # à desconexão para preservar os posts já coletados.
    connected: bool
    # `real` ou `demo` — de onde o dado desta conta veio. Vai no payload porque
    # a tela precisa rotular a conexão de demonstração: mostrar métrica simulada
    # sem dizer que é simulada é apresentar dado inventado como medido.
    connection_mode: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Campos *_encrypted deliberadamente omitidos.


class SocialAccountCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    influencer_id: uuid.UUID
    platform: Platform
    handle: Handle
    platform_user_id: IdDePlataforma = None
    follower_count: Seguidores = 0


class SocialAccountUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Campo obrigatório no banco não é `Optional` aqui. O `None` padrão só marca
    # "não enviado" — a rota aplica `exclude_unset` —, e um `null` explícito vira
    # erro de validação no próprio campo, em vez de erro 500 no banco.
    handle: Handle = None
    platform_user_id: IdDePlataforma = None
    follower_count: Seguidores = None
