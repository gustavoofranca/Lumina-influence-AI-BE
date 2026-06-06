"""Blueprint /api/v1/influencers — CRUD com filtros, escopado por agência."""
from __future__ import annotations

from flask import Blueprint, request
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import Influencer, InfluencerStatus, Platform, UserRole
from src.schemas.influencer import (
    InfluencerCreateIn,
    InfluencerOut,
    InfluencerUpdateIn,
)
from src.services import dashboard_service
from src.services.influencer_service import build_influencer_query
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok, paginated
from src.utils.validation import parse_enum_arg, parse_json

bp = Blueprint("influencers", __name__, url_prefix="/api/v1/influencers")


def _dump(inf: Influencer) -> dict:
    return InfluencerOut.model_validate(inf).model_dump(mode="json")


@bp.get("")
@require_auth
def list_influencers():
    status = parse_enum_arg(InfluencerStatus, request.args.get("status"))
    platform = parse_enum_arg(Platform, request.args.get("platform"))
    search = request.args.get("search")
    follower_min = request.args.get("follower_min", type=int)
    follower_max = request.args.get("follower_max", type=int)

    stmt = build_influencer_query(
        current_agency_id(),
        search=search,
        status=status,
        platform=platform,
        follower_min=follower_min,
        follower_max=follower_max,
    )
    page = paginate(stmt)
    return paginated([_dump(i) for i in page.items], page)


@bp.get("/<influencer_id>")
@require_auth
def get_influencer(influencer_id):
    inf = get_scoped_or_404(Influencer, influencer_id)
    return ok(_dump(inf))


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def create_influencer():
    payload = parse_json(InfluencerCreateIn)
    inf = Influencer(
        agency_id=current_agency_id(),
        display_name=payload.display_name,
        niche=payload.niche,
        bio=payload.bio,
        status=payload.status,
    )
    db.session.add(inf)
    db.session.commit()
    return created(_dump(inf))


@bp.patch("/<influencer_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def update_influencer(influencer_id):
    inf = get_scoped_or_404(Influencer, influencer_id)
    payload = parse_json(InfluencerUpdateIn)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(inf, field, value)
    db.session.commit()
    return ok(_dump(inf))


@bp.delete("/<influencer_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def delete_influencer(influencer_id):
    inf = get_scoped_or_404(Influencer, influencer_id)
    # Influencer não tem soft delete — delete físico (cascade nas contas/posts).
    db.session.delete(inf)
    db.session.commit()
    return no_content()


# --------------------------------------------------------------------------
# Endpoints de dashboard (B5) — análise individual e grid de posts
# --------------------------------------------------------------------------
@bp.get("/<influencer_id>/analysis")
@require_auth
def influencer_analysis(influencer_id):
    """Diagnóstico IA completo do influencer (tela de análise individual)."""
    inf = get_scoped_or_404(Influencer, influencer_id)
    # social_accounts são lazy-loaded dentro da request quando o service acessa.
    data = dashboard_service.influencer_analysis(inf)
    return ok(data)


@bp.get("/<influencer_id>/posts")
@require_auth
def influencer_posts(influencer_id):
    """Grid de posts analisados do influencer (tab Posts Analisados)."""
    inf = get_scoped_or_404(Influencer, influencer_id)
    limit = request.args.get("limit", 20, type=int) or 20
    limit = min(max(limit, 1), 100)
    data = dashboard_service.influencer_posts(inf, limit=limit)
    return ok(data, meta={"limit": limit, "count": len(data)})


@bp.post("/<influencer_id>/sync")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def sync_influencer(influencer_id):
    """Força sync das contas sociais do influencer (real se conectado, simulado se não)."""
    from src.services import integration_service

    inf = get_scoped_or_404(Influencer, influencer_id)
    result = integration_service.sync_influencer(inf)
    return ok(result)
