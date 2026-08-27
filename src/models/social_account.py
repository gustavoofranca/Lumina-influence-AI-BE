"""Modelo SocialAccount — conta social conectada via OAuth."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import Platform
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.influencer import Influencer
    from src.models.post import Post


class SocialAccount(Base, TimestampMixin):
    """Conta social do influencer numa plataforma específica.

    Tokens são sempre criptografados em repouso (Fernet — utils/crypto.py).
    """

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint(
            "influencer_id", "platform", "handle", name="uq_social_accounts_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    influencer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform"), nullable=False, index=True
    )
    handle: Mapped[str] = mapped_column(String(120), nullable=False)
    platform_user_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    follower_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Tokens criptografados (Fernet) — armazenados como TEXT.
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def connected(self) -> bool:
        """Há token guardado para coletar da plataforma.

        Desconectar apaga os tokens e preserva a conta, para não levar junto o
        histórico de posts. Sem esta distinção no payload, a interface trata
        como conectada qualquer conta que exista — inclusive as do seed, que
        nunca passaram por OAuth.
        """
        return self.access_token_encrypted is not None

    influencer: Mapped["Influencer"] = relationship(back_populates="social_accounts")
    posts: Mapped[list["Post"]] = relationship(
        back_populates="social_account", cascade="all, delete-orphan"
    )
