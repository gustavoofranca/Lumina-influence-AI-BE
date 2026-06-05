"""Blueprint /api/v1/agencies — usuário só enxerga/edita a própria agência."""
from __future__ import annotations

from flask import Blueprint, g
from sqlalchemy import select

from src.extensions import db
from src.models import Agency, Plan, UserRole
from src.schemas.agency import AgencyOut, AgencyUpdateIn
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, require_role
from src.utils.errors import NotFoundError, ValidationError
from src.utils.responses import no_content, ok
from src.utils.validation import parse_json

bp = Blueprint("agencies", __name__, url_prefix="/api/v1/agencies")


def _load_own_agency() -> Agency:
    agency = db.session.scalar(
        select(Agency).where(
            Agency.id == current_agency_id(), Agency.deleted_at.is_(None)
        )
    )
    if agency is None:
        raise NotFoundError("Agency não encontrada")
    return agency


@bp.get("")
@require_auth
def list_agencies():
    """Lista contém apenas a própria agência (isolamento multi-tenant)."""
    agency = _load_own_agency()
    return ok([AgencyOut.model_validate(agency).model_dump(mode="json")])


@bp.get("/<agency_id>")
@require_auth
def get_agency(agency_id):
    agency = _load_own_agency()
    if str(agency.id) != str(agency_id):
        raise NotFoundError("Agency não encontrada")
    return ok(AgencyOut.model_validate(agency).model_dump(mode="json"))


@bp.patch("/<agency_id>")
@require_auth
@require_role(UserRole.ADMIN)
def update_agency(agency_id):
    agency = _load_own_agency()
    if str(agency.id) != str(agency_id):
        raise NotFoundError("Agency não encontrada")

    payload = parse_json(AgencyUpdateIn)
    data = payload.model_dump(exclude_unset=True)

    if "plan_id" in data and data["plan_id"] is not None:
        plan = db.session.get(Plan, data["plan_id"])
        if plan is None:
            raise ValidationError("plan_id inexistente", details={"plan_id": str(data["plan_id"])})

    for field, value in data.items():
        setattr(agency, field, value)
    db.session.commit()
    return ok(AgencyOut.model_validate(agency).model_dump(mode="json"))


@bp.delete("/<agency_id>")
@require_auth
@require_role(UserRole.ADMIN)
def delete_agency(agency_id):
    from datetime import datetime, timezone

    agency = _load_own_agency()
    if str(agency.id) != str(agency_id):
        raise NotFoundError("Agency não encontrada")
    agency.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return no_content()
