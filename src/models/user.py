"""Modelo User — autenticado via OAuth (Google/Microsoft)."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import OAuthProvider, UserRole
from src.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from src.models.agency import Agency
    from src.models.oauth_state import OAuthState
    from src.models.report import Report


class User(Base, TimestampMixin, SoftDeleteMixin):
    """Usuário do app. Login somente via OAuth — nunca tem senha local."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_id", name="uq_users_oauth_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oauth_provider: Mapped[OAuthProvider] = mapped_column(
        SAEnum(OAuthProvider, name="oauth_provider"), nullable=False
    )
    oauth_id: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.MEMBER
    )
    agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=True, index=True
    )

    agency: Mapped[Optional["Agency"]] = relationship(back_populates="users")
    oauth_states: Mapped[list["OAuthState"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    generated_reports: Mapped[list["Report"]] = relationship(
        back_populates="generated_by", foreign_keys="Report.generated_by_user_id"
    )
