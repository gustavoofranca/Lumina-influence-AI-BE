"""Blueprint /api/v1/campaigns — CRUD com filtros de status e período."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, request

from src.extensions import db
from src.models import Campaign, CampaignStatus, UserRole
from src.schemas.campaign import CampaignCreateIn, CampaignOut, CampaignUpdateIn
from src.services.campaign_service import build_campaign_query
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import ValidationError
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok, paginated
from src.utils.validation import parse_enum_arg, parse_json

bp = Blueprint("campaigns", __name__, url_prefix="/api/v1/campaigns")


def _dump(c: Campaign) -> dict:
    return CampaignOut.model_validate(c).model_dump(mode="json")


def _parse_date_arg(name: str) -> date | None:
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(
            f"Data inválida em {name} (use YYYY-MM-DD)", details={"received": raw}
        ) from exc


@bp.get("")
@require_auth
def list_campaigns():
    status = parse_enum_arg(CampaignStatus, request.args.get("status"))
    stmt = build_campaign_query(
        current_agency_id(),
        status=status,
        starts_after=_parse_date_arg("starts_after"),
        ends_before=_parse_date_arg("ends_before"),
        search=request.args.get("search"),
    )
    page = paginate(stmt)
    return paginated([_dump(c) for c in page.items], page)


@bp.get("/<campaign_id>")
@require_auth
def get_campaign(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    return ok(_dump(camp))


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def create_campaign():
    payload = parse_json(CampaignCreateIn)
    camp = Campaign(
        agency_id=current_agency_id(),
        brand_name=payload.brand_name,
        title=payload.title,
        period_start=payload.period_start,
        period_end=payload.period_end,
        budget_brl_cents=payload.budget_brl_cents,
        status=payload.status,
    )
    db.session.add(camp)
    db.session.commit()
    return created(_dump(camp))


@bp.patch("/<campaign_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def update_campaign(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    payload = parse_json(CampaignUpdateIn)
    data = payload.model_dump(exclude_unset=True)

    # Valida período resultante após o merge.
    new_start = data.get("period_start", camp.period_start)
    new_end = data.get("period_end", camp.period_end)
    if new_end < new_start:
        raise ValidationError("period_end não pode ser anterior a period_start")

    for field, value in data.items():
        setattr(camp, field, value)
    db.session.commit()
    return ok(_dump(camp))


@bp.delete("/<campaign_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def delete_campaign(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    db.session.delete(camp)
    db.session.commit()
    return no_content()
