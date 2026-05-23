"""Modelo OAuthState — controle do fluxo OAuth (CSRF + PKCE)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import OAuthProvider
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User


class OAuthState(Base, TimestampMixin):
    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[OAuthProvider] = mapped_column(
        SAEnum(OAuthProvider, name="oauth_provider", create_type=False), nullable=False
    )
    state_token: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    code_verifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="oauth_states")
