"""Modelos Post e Comment (amostra para NLP)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import PostType
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.ai_analysis import AIAnalysis
    from src.models.campaign import Campaign
    from src.models.social_account import SocialAccount


class Post(Base, TimestampMixin):
    """Post coletado de uma rede social."""

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint(
            "social_account_id", "platform_post_id", name="uq_posts_platform_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    social_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("social_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform_post_id: Mapped[str] = mapped_column(String(160), nullable=False)
    post_type: Mapped[PostType] = mapped_column(
        SAEnum(PostType, name="post_type"), nullable=False
    )
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Métricas — alcance e engajamento
    reach_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reach_organic: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reach_paid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    saves: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Métricas de vídeo (nullable porque nem todo post é vídeo)
    avg_watch_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retention_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    social_account: Mapped["SocialAccount"] = relationship(back_populates="posts")
    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    ai_analyses: Mapped[list["AIAnalysis"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class Comment(Base, TimestampMixin):
    """Amostra de comentários do post — usado pra NLP/sentimento."""

    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint(
            "post_id", "platform_comment_id", name="uq_comments_platform_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_comment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_handle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    post: Mapped["Post"] = relationship(back_populates="comments")
