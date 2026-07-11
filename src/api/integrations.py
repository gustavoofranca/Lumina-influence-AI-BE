"""Blueprint /api/v1/integrations — OAuth das redes sociais (connect/callback/disconnect)."""
from __future__ import annotations

import uuid

from flask import Blueprint, current_app, request, url_for

from src.models import UserRole
from src.schemas.social_account import SocialAccountOut
from src.services import integration_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import ValidationError
from src.utils.responses import ok
from src.models import Influencer

bp = Blueprint("integrations", __name__, url_prefix="/api/v1/integrations")


def _redirect_uri(platform: str) -> str:
    base = current_app.config.get("OAUTH_REDIRECT_BASE")
    path = url_for("integrations.callback", platform=platform)
    if base:
        return base.rstrip("/") + path
    return url_for("integrations.callback", platform=platform, _external=True)


@bp.get("/<platform>/connect")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def connect(platform):
    """Gera a URL de autorização OAuth pra conectar uma conta ao influencer."""
    plat = integration_service.parse_platform(platform)
    influencer_id = request.args.get("influencer_id")
    if not influencer_id:
        raise ValidationError("influencer_id é obrigatório")
    influencer = get_scoped_or_404(Influencer, influencer_id)

    auth_url = integration_service.build_connect_url(
        influencer=influencer,
        platform=plat,
        agency_id=current_agency_id(),
        redirect_uri=_redirect_uri(platform),
    )
    return ok({"auth_url": auth_url, "platform": platform})


@bp.get("/<platform>/callback")
@require_auth
def callback(platform):
    """Recebe o code, troca por tokens, criptografa e persiste a SocialAccount."""
    plat = integration_service.parse_platform(platform)
    error = request.args.get("error")
    if error:
        raise ValidationError(
            f"Provedor retornou erro: {error}",
            details={"description": request.args.get("error_description")},
        )
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        raise ValidationError("Parâmetros code/state ausentes")

    account = integration_service.handle_callback(
        platform=plat,
        code=code,
        state=state,
        agency_id=current_agency_id(),
        redirect_uri=_redirect_uri(platform),
    )
    return ok(SocialAccountOut.model_validate(account).model_dump(mode="json"), status=201)


@bp.post("/<platform>/disconnect/<social_account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def disconnect(platform, social_account_id):
    """Remove os tokens da conta (desconecta), mantendo o histórico de posts."""
    integration_service.parse_platform(platform)  # valida nome
    try:
        sid = uuid.UUID(social_account_id)
    except ValueError as exc:
        from src.utils.errors import NotFoundError

        raise NotFoundError("SocialAccount não encontrada") from exc
    integration_service.disconnect_account(social_account_id=sid, agency_id=current_agency_id())
    return ok({"disconnected": str(sid)})
