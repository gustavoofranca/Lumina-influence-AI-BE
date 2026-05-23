"""Modelo ApiUsageLog — log de uso de APIs externas pra controle de cota."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.agency import Agency


class ApiUsageLog(Base, TimestampMixin):
    __tablename__ = "api_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    agency: Mapped["Agency"] = relationship(back_populates="api_usage_logs")
