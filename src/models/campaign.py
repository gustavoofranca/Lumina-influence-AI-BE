"""Modelos Campaign e CampaignInfluencer (associativa)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Date,
    Enum as SAEnum,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import CampaignStatus
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.agency import Agency
    from src.models.influencer import Influencer
    from src.models.post import Post
    from src.models.report import Report


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    budget_brl_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="campaign_status"),
        nullable=False,
        default=CampaignStatus.DRAFT,
        index=True,
    )

    agency: Mapped["Agency"] = relationship(back_populates="campaigns")
    influencer_links: Mapped[list["CampaignInfluencer"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="campaign")
    reports: Mapped[list["Report"]] = relationship(back_populates="campaign")


class CampaignInfluencer(Base, TimestampMixin):
    """Associativa N:N entre Campaign e Influencer com payload (fee, deliverables)."""

    __tablename__ = "campaign_influencers"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "influencer_id", name="uq_campaign_influencer_pair"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    influencer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_brl_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    deliverables: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="influencer_links")
    influencer: Mapped["Influencer"] = relationship(back_populates="campaign_links")
