"""Código de recuperação do 2FA: entra quando o celular com o app se perdeu.

O banco guarda o HMAC-SHA-256 do código com uma chave derivada da `FERNET_KEY`,
e não o código. Hash simples não bastaria: o código tem ~40 bits, e quem
levasse uma cópia do banco os testaria todos offline. Com a chave fora do
banco, a cópia sozinha não serve para nada.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User


class CodigoRecuperacao(Base, TimestampMixin):
    __tablename__ = "codigos_recuperacao"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    usado_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="codigos_recuperacao")
