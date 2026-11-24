"""Token de uso único enviado por e-mail (verificação e redefinição de senha).

O banco guarda só o SHA-256 do token. O token em si existe apenas no link do
e-mail: quem lê o banco — um backup vazado, por exemplo — não consegue usar
nenhum link pendente.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import FinalidadeToken
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User


class AuthToken(Base, TimestampMixin):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finalidade: Mapped[FinalidadeToken] = mapped_column(
        SAEnum(FinalidadeToken, name="finalidade_token"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="auth_tokens")
