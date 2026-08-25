"""Blueprint /api/v1/plans — somente leitura (catálogo global de planos)."""
from __future__ import annotations

from flask import Blueprint

from src.schemas.plan import PlanOut
from src.services import plan_service
from src.utils.auth_decorators import require_auth
from src.utils.responses import ok

bp = Blueprint("plans", __name__, url_prefix="/api/v1/plans")


def _dump(plan) -> dict:
    return PlanOut.model_validate(plan).model_dump(mode="json")


@bp.get("")
@require_auth
def list_plans():
    return ok([_dump(p) for p in plan_service.list_plans()])


@bp.get("/<plan_id>")
@require_auth
def get_plan(plan_id):
    return ok(_dump(plan_service.get_plan_or_404(plan_id)))
