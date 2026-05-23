"""Modelo Influencer — auditado pela agência."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import InfluencerStatus
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.agency import Agency
    from src.models.campaign import CampaignInfluencer
    from src.models.social_account import SocialAccount


class Influencer(Base, TimestampMixin):
    __tablename__ = "influencers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    niche: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    bio: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[InfluencerStatus] = mapped_column(
        SAEnum(InfluencerStatus, name="influencer_status"),
        nullable=False,
        default=InfluencerStatus.ACTIVE,
        index=True,
    )

    agency: Mapped["Agency"] = relationship(back_populates="influencers")
    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="influencer", cascade="all, delete-orphan"
    )
    campaign_links: Mapped[list["CampaignInfluencer"]] = relationship(
        back_populates="influencer", cascade="all, delete-orphan"
    )
