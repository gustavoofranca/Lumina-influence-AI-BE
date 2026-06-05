"""Lógica de consulta/filtragem de campanhas."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, select

from src.models import Campaign, CampaignStatus


def build_campaign_query(
    agency_id: uuid.UUID,
    *,
    status: CampaignStatus | None = None,
    starts_after: date | None = None,
    ends_before: date | None = None,
    search: str | None = None,
) -> Select:
    """SELECT de campanhas escopado por agência, com filtros de status e período."""
    stmt = (
        select(Campaign)
        .where(Campaign.agency_id == agency_id)
        .order_by(Campaign.period_start.desc())
    )

    if status is not None:
        stmt = stmt.where(Campaign.status == status)
    if starts_after is not None:
        stmt = stmt.where(Campaign.period_start >= starts_after)
    if ends_before is not None:
        stmt = stmt.where(Campaign.period_end <= ends_before)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Campaign.brand_name.ilike(like))

    return stmt
