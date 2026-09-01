"""Blueprint /api/v1/campaigns — CRUD com filtros de status e período."""
from __future__ import annotations

import uuid
from datetime import date

from flask import Blueprint, request

from src.models import Campaign, CampaignStatus, UserRole
from src.schemas.campaign import (
    CampaignCreateIn,
    CampaignOut,
    CampaignParticipantIn,
    CampaignUpdateIn,
)
from src.services import dashboard_service
from src.services import campaign_service
from src.services.campaign_service import (
    build_campaign_query,
    participants_by_campaign,
    validate_participants,
)
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import NotFoundError, ValidationError
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
    participants = participants_by_campaign([c.id for c in page.items])
    items = [
        {**_dump(c), "participants": participants.get(c.id, [])} for c in page.items
    ]
    return paginated(items, page)


@bp.get("/<campaign_id>")
@require_auth
def get_campaign(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    participants = participants_by_campaign([camp.id])
    return ok({**_dump(camp), "participants": participants[camp.id]})


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def create_campaign():
    payload = parse_json(CampaignCreateIn)
    agency_id = current_agency_id()
    # Antes de qualquer INSERT: id inválido aqui abortaria a criação no meio.
    validate_participants(payload.participants, agency_id)

    camp = campaign_service.create_campaign(
        agency_id=agency_id, payload=payload, participants=payload.participants
    )

    participants = participants_by_campaign([camp.id])
    return created({**_dump(camp), "participants": participants[camp.id]})


@bp.patch("/<campaign_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def update_campaign(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    payload = parse_json(CampaignUpdateIn)
    updated = campaign_service.apply_update(camp, payload.model_dump(exclude_unset=True))
    return ok(_dump(updated))


@bp.post("/<campaign_id>/participants")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def add_campaign_participant(campaign_id):
    """Vincula um criador a uma campanha já existente."""
    campaign = get_scoped_or_404(Campaign, campaign_id)
    payload = parse_json(CampaignParticipantIn)
    return created(campaign_service.add_participant(
        campaign, payload, current_agency_id()
    ))


@bp.delete("/<campaign_id>/participants/<influencer_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def remove_campaign_participant(campaign_id, influencer_id):
    """Desvincula o criador. O criador e as publicações dele permanecem."""
    campaign = get_scoped_or_404(Campaign, campaign_id)
    try:
        alvo = uuid.UUID(str(influencer_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("Criador não está vinculado a esta campanha") from exc
    campaign_service.remove_participant(campaign, alvo)
    return no_content()


@bp.delete("/<campaign_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def delete_campaign(campaign_id):
    campaign_service.delete_campaign(get_scoped_or_404(Campaign, campaign_id))
    return no_content()


# --------------------------------------------------------------------------
# Endpoint de dashboard (B5) — benchmarking entre influencers da campanha
# --------------------------------------------------------------------------
@bp.get("/<campaign_id>/benchmarking")
@require_auth
def campaign_benchmarking(campaign_id):
    camp = get_scoped_or_404(Campaign, campaign_id)
    data = dashboard_service.campaign_benchmarking(camp)
    return ok(data)
