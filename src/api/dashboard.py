"""Blueprint /api/v1/dashboard — agregações de overview e rede."""
from __future__ import annotations

import uuid

from flask import Blueprint, request

from src.services import dashboard_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id
from src.utils.errors import ValidationError
from src.utils.responses import ok

bp = Blueprint("dashboard", __name__, url_prefix="/api/v1/dashboard")


@bp.get("/overview")
@require_auth
def overview():
    period = request.args.get("period", "30d")
    campaign_raw = request.args.get("campaign_id")
    campaign_id = None
    if campaign_raw and campaign_raw != "all":
        try:
            campaign_id = uuid.UUID(campaign_raw)
        except ValueError as exc:
            raise ValidationError("campaign_id inválido", details={"received": campaign_raw}) from exc

    data = dashboard_service.overview(
        current_agency_id(), period=period, campaign_id=campaign_id
    )
    return ok(data, meta={"period": period, "campaign_id": campaign_raw or "all"})


@bp.get("/network-density")
@require_auth
def network_density():
    data = dashboard_service.network_density(current_agency_id())
    return ok(data)
