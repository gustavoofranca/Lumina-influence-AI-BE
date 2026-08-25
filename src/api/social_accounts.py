"""Blueprint /api/v1/social-accounts — CRUD escopado via influencer da agência.

SocialAccount não tem agency_id direto: o escopo vem do Influencer dono.
Tokens criptografados nunca são expostos (SocialAccountOut os omite).
"""
from __future__ import annotations

from flask import Blueprint, request

from src.models import Influencer, SocialAccount, UserRole
from src.schemas.social_account import (
    SocialAccountCreateIn,
    SocialAccountOut,
    SocialAccountUpdateIn,
)
from src.services import social_account_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok, paginated
from src.utils.validation import parse_json

bp = Blueprint("social_accounts", __name__, url_prefix="/api/v1/social-accounts")


def _dump(sa: SocialAccount) -> dict:
    return SocialAccountOut.model_validate(sa).model_dump(mode="json")


def _load_scoped_account(account_id) -> SocialAccount:
    return social_account_service.load_scoped_account(account_id, current_agency_id())


@bp.get("")
@require_auth
def list_social_accounts():
    page = paginate(social_account_service.build_account_query(
        current_agency_id(), influencer_id=request.args.get("influencer_id")
    ))
    return paginated([_dump(s) for s in page.items], page)


@bp.get("/<account_id>")
@require_auth
def get_social_account(account_id):
    sa = _load_scoped_account(account_id)
    return ok(_dump(sa))


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def create_social_account():
    payload = parse_json(SocialAccountCreateIn)
    # Garante que o influencer alvo pertence à agência do usuário.
    get_scoped_or_404(Influencer, payload.influencer_id)

    sa = social_account_service.create_account(
        influencer_id=payload.influencer_id,
        platform=payload.platform,
        handle=payload.handle,
        platform_user_id=payload.platform_user_id,
        follower_count=payload.follower_count,
    )
    return created(_dump(sa))


@bp.patch("/<account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def update_social_account(account_id):
    sa = _load_scoped_account(account_id)
    payload = parse_json(SocialAccountUpdateIn)
    updated = social_account_service.apply_update(sa, payload.model_dump(exclude_unset=True))
    return ok(_dump(updated))


@bp.delete("/<account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def delete_social_account(account_id):
    social_account_service.delete_account(_load_scoped_account(account_id))
    return no_content()
