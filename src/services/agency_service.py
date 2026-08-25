"""Consumo da agência frente aos limites do plano."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Agency,
    AIAnalysis,
    Influencer,
    Post,
    Report,
    SocialAccount,
)
from src.services import plan_service
from src.utils.errors import NotFoundError, ValidationError


def load_own_agency(agency_id: uuid.UUID) -> Agency:
    """A única agência que o usuário pode ver é a dele. 404 para qualquer outra."""
    agency = db.session.scalar(
        select(Agency).where(Agency.id == agency_id, Agency.deleted_at.is_(None))
    )
    if agency is None:
        raise NotFoundError("Agency não encontrada")
    return agency


def soft_delete(agency: Agency) -> None:
    agency.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


def apply_update(agency: Agency, data: dict) -> Agency:
    """Aplica o PATCH. plan_id só passa se o plano existir."""
    if data.get("plan_id") is not None and plan_service.find_plan(data["plan_id"]) is None:
        raise ValidationError("plan_id inexistente", details={"plan_id": str(data["plan_id"])})

    for field, value in data.items():
        setattr(agency, field, value)
    db.session.commit()
    return agency


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _count_influencers(agency_id: uuid.UUID) -> int:
    return int(db.session.scalar(
        select(func.count(Influencer.id)).where(Influencer.agency_id == agency_id)
    ) or 0)


def _count_analyses_this_month(agency_id: uuid.UUID, now: datetime) -> int:
    return int(db.session.scalar(
        select(func.count(AIAnalysis.id))
        .join(Post, AIAnalysis.post_id == Post.id)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == agency_id)
        .where(AIAnalysis.analyzed_at >= _month_start(now))
    ) or 0)


def _count_reports(agency_id: uuid.UUID) -> int:
    return int(db.session.scalar(
        select(func.count(Report.id)).where(Report.agency_id == agency_id)
    ) or 0)


def usage(agency: Agency) -> dict:
    """Uso atual x limite do plano.

    `limit` vem nulo quando o plano não impõe teto para aquele recurso — a tela
    precisa distinguir "sem limite" de "limite zero".
    """
    now = datetime.now(timezone.utc)
    plan = agency.plan

    return {
        "influencers": {
            "used": _count_influencers(agency.id),
            "limit": plan.max_influencers if plan else None,
        },
        "analyses": {
            "used": _count_analyses_this_month(agency.id, now),
            "limit": plan.max_analyses_per_month if plan else None,
            "period": "current_month",
        },
        "reports": {
            "used": _count_reports(agency.id),
            "limit": None,
        },
    }
