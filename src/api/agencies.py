"""Blueprint /api/v1/agencies — usuário só enxerga/edita a própria agência."""
from __future__ import annotations

from flask import Blueprint

from src.models import UserRole
from src.schemas.agency import AgencyOut, AgencyUpdateIn
from src.services import agency_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, require_role
from src.utils.errors import NotFoundError
from src.utils.responses import no_content, ok
from src.utils.validation import parse_json

bp = Blueprint("agencies", __name__, url_prefix="/api/v1/agencies")


def _dump(agency) -> dict:
    return AgencyOut.model_validate(agency).model_dump(mode="json")


def _own_agency_or_404(agency_id):
    """Carrega a própria agência e confere que é a pedida na URL."""
    agency = agency_service.load_own_agency(current_agency_id())
    if str(agency.id) != str(agency_id):
        raise NotFoundError("Agency não encontrada")
    return agency


@bp.get("")
@require_auth
def list_agencies():
    """Lista contém apenas a própria agência (isolamento multi-tenant)."""
    agency = agency_service.load_own_agency(current_agency_id())
    return ok([_dump(agency)])


@bp.get("/<agency_id>")
@require_auth
def get_agency(agency_id):
    return ok(_dump(_own_agency_or_404(agency_id)))


@bp.get("/<agency_id>/usage")
@require_auth
def agency_usage(agency_id):
    """Consumo do mês frente aos limites do plano."""
    return ok(agency_service.usage(_own_agency_or_404(agency_id)))


@bp.patch("/<agency_id>")
@require_auth
@require_role(UserRole.ADMIN)
def update_agency(agency_id):
    agency = _own_agency_or_404(agency_id)
    payload = parse_json(AgencyUpdateIn)
    updated = agency_service.apply_update(agency, payload.model_dump(exclude_unset=True))
    return ok(_dump(updated))


@bp.delete("/<agency_id>")
@require_auth
@require_role(UserRole.ADMIN)
def delete_agency(agency_id):
    agency_service.soft_delete(_own_agency_or_404(agency_id))
    return no_content()
