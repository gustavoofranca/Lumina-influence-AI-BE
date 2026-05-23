"""Modelos Plan e Agency."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from src.models.api_usage import ApiUsageLog
    from src.models.campaign import Campaign
    from src.models.influencer import Influencer
    from src.models.report import Report
    from src.models.user import User


class Plan(Base, TimestampMixin):
    """Planos comerciais (Free, Agency, etc.)."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    max_influencers: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_analyses_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    allow_benchmarking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_brl_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    agencies: Mapped[list["Agency"]] = relationship(back_populates="plan")


class Agency(Base, TimestampMixin, SoftDeleteMixin):
    """Agência cliente. Cada usuário pertence a uma."""

    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    cnpj: Mapped[Optional[str]] = mapped_column(String(18), nullable=True, unique=True)
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    plan: Mapped[Optional["Plan"]] = relationship(back_populates="agencies")
    users: Mapped[list["User"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
    influencers: Mapped[list["Influencer"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
    api_usage_logs: Mapped[list["ApiUsageLog"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
