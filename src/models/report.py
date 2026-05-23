"""Modelo Report — relatório PDF gerado pela agência."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import ReportFormat
from src.models.base import Base, JSONField, TimestampMixin

if TYPE_CHECKING:
    from src.models.agency import Agency
    from src.models.campaign import Campaign
    from src.models.user import User


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    generated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    format: Mapped[ReportFormat] = mapped_column(
        SAEnum(ReportFormat, name="report_format"),
        nullable=False,
        default=ReportFormat.PDF,
    )
    sections: Mapped[Optional[dict]] = mapped_column(JSONField, nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    agency: Mapped["Agency"] = relationship(back_populates="reports")
    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="reports")
    generated_by: Mapped[Optional["User"]] = relationship(
        back_populates="generated_reports", foreign_keys=[generated_by_user_id]
    )
