"""Blueprint /api/v1/plans — somente leitura (catálogo global de planos)."""
from __future__ import annotations

import uuid

from flask import Blueprint
from sqlalchemy import select

from src.extensions import db
from src.models import Plan
from src.schemas.plan import PlanOut
from src.utils.auth_decorators import require_auth
from src.utils.errors import NotFoundError
from src.utils.responses import ok

bp = Blueprint("plans", __name__, url_prefix="/api/v1/plans")


@bp.get("")
@require_auth
def list_plans():
    plans = db.session.scalars(
        select(Plan).order_by(Plan.price_brl_cents.asc())
    ).all()
    return ok([PlanOut.model_validate(p).model_dump(mode="json") for p in plans])


@bp.get("/<plan_id>")
@require_auth
def get_plan(plan_id):
    try:
        pid = uuid.UUID(plan_id)
    except ValueError as exc:
        raise NotFoundError("Plan não encontrado") from exc
    plan = db.session.get(Plan, pid)
    if plan is None:
        raise NotFoundError("Plan não encontrado")
    return ok(PlanOut.model_validate(plan).model_dump(mode="json"))
