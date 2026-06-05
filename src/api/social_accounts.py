"""Blueprint /api/v1/social-accounts — CRUD escopado via influencer da agência.

SocialAccount não tem agency_id direto: o escopo vem do Influencer dono.
Tokens criptografados nunca são expostos (SocialAccountOut os omite).
"""
from __future__ import annotations

import uuid

from flask import Blueprint, request
from sqlalchemy import select

from src.extensions import db
from src.models import Influencer, SocialAccount, UserRole
from src.schemas.social_account import (
    SocialAccountCreateIn,
    SocialAccountOut,
    SocialAccountUpdateIn,
)
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import ConflictError, NotFoundError
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok, paginated
from src.utils.validation import parse_json

bp = Blueprint("social_accounts", __name__, url_prefix="/api/v1/social-accounts")


def _dump(sa: SocialAccount) -> dict:
    return SocialAccountOut.model_validate(sa).model_dump(mode="json")


def _load_scoped_account(account_id) -> SocialAccount:
    """Carrega a conta garantindo que o influencer dono é da agência do usuário."""
    try:
        sid = uuid.UUID(str(account_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("SocialAccount não encontrada") from exc
    sa = db.session.scalar(
        select(SocialAccount)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(SocialAccount.id == sid, Influencer.agency_id == current_agency_id())
    )
    if sa is None:
        raise NotFoundError("SocialAccount não encontrada")
    return sa


@bp.get("")
@require_auth
def list_social_accounts():
    stmt = (
        select(SocialAccount)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == current_agency_id())
        .order_by(SocialAccount.created_at.desc())
    )
    influencer_id = request.args.get("influencer_id")
    if influencer_id:
        try:
            stmt = stmt.where(SocialAccount.influencer_id == uuid.UUID(influencer_id))
        except ValueError:
            stmt = stmt.where(SocialAccount.influencer_id == uuid.uuid4())  # no match

    page = paginate(stmt)
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

    dup = db.session.scalar(
        select(SocialAccount).where(
            SocialAccount.influencer_id == payload.influencer_id,
            SocialAccount.platform == payload.platform,
            SocialAccount.handle == payload.handle,
        )
    )
    if dup is not None:
        raise ConflictError(
            "Conta já cadastrada para este influencer/plataforma/handle",
            code="social_account_exists",
        )

    sa = SocialAccount(
        influencer_id=payload.influencer_id,
        platform=payload.platform,
        handle=payload.handle,
        platform_user_id=payload.platform_user_id,
        follower_count=payload.follower_count,
    )
    db.session.add(sa)
    db.session.commit()
    return created(_dump(sa))


@bp.patch("/<account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def update_social_account(account_id):
    sa = _load_scoped_account(account_id)
    payload = parse_json(SocialAccountUpdateIn)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(sa, field, value)
    db.session.commit()
    return ok(_dump(sa))


@bp.delete("/<account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def delete_social_account(account_id):
    sa = _load_scoped_account(account_id)
    db.session.delete(sa)
    db.session.commit()
    return no_content()
