"""Catálogo de planos — leitura apenas."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from src.extensions import db
from src.models import Plan
from src.utils.errors import NotFoundError


def list_plans() -> list[Plan]:
    """Catálogo global, do mais barato para o mais caro."""
    return list(db.session.scalars(select(Plan).order_by(Plan.price_brl_cents.asc())).all())


def get_plan_or_404(plan_id: str | uuid.UUID) -> Plan:
    try:
        pid = plan_id if isinstance(plan_id, uuid.UUID) else uuid.UUID(str(plan_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("Plan não encontrado") from exc

    plan = db.session.get(Plan, pid)
    if plan is None:
        raise NotFoundError("Plan não encontrado")
    return plan


def find_plan(plan_id: uuid.UUID) -> Plan | None:
    """Busca sem levantar — usado na validação de plan_id ao editar agência."""
    return db.session.get(Plan, plan_id)
