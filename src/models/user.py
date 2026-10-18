"""Modelo User — autenticado por senha local, por OAuth (Google/Microsoft), ou pelos dois."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import OAuthProvider, UserRole
from src.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from src.models.auth_token import AuthToken
    from src.models.agency import Agency
    from src.models.oauth_state import OAuthState
    from src.models.report import Report


class User(Base, TimestampMixin, SoftDeleteMixin):
    """Usuário do app. Entra por e-mail e senha, por OAuth, ou pelos dois.

    `oauth_provider`/`oauth_id` ficam nulos em conta só com senha;
    `password_hash` fica nulo em conta só com OAuth.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_id", name="uq_users_oauth_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oauth_provider: Mapped[Optional[OAuthProvider]] = mapped_column(
        SAEnum(OAuthProvider, name="oauth_provider"), nullable=True
    )
    oauth_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verificado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Token com `iat` anterior a este instante é recusado. É o que derruba as
    # outras sessões quando a senha muda — ver ADR-0013, que revisa a ADR-001.
    sessoes_validas_desde: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Evidência do consentimento (LGPD, art. 8º): quando a pessoa aceitou.
    termos_aceitos_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    auth_tokens: Mapped[list["AuthToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def email_verified(self) -> bool:
        return self.email_verificado_em is not None

    @property
    def terms_accepted(self) -> bool:
        return self.termos_aceitos_em is not None
