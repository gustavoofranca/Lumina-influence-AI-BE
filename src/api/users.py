"""Blueprint /api/v1/users — gestão de membros da própria agência."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, g
from sqlalchemy import select

from src.extensions import db
from src.models import User, UserRole
from src.schemas.user import UserCreateIn, UserOut, UserUpdateIn
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import ConflictError, ForbiddenError, ValidationError
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok
from src.utils.validation import parse_json

bp = Blueprint("users", __name__, url_prefix="/api/v1/users")


def _dump(user: User) -> dict:
    return UserOut.model_validate(user).model_dump(mode="json")


@bp.get("")
@require_auth
def list_users():
    stmt = (
        select(User)
        .where(User.agency_id == current_agency_id(), User.deleted_at.is_(None))
        .order_by(User.name.asc())
    )
    page = paginate(stmt)
    from src.utils.responses import paginated

    return paginated([_dump(u) for u in page.items], page)


@bp.get("/<user_id>")
@require_auth
def get_user(user_id):
    user = get_scoped_or_404(User, user_id)
    return ok(_dump(user))


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN)
def create_user():
    payload = parse_json(UserCreateIn)

    existing = db.session.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise ConflictError("Email já cadastrado", details={"email": payload.email})

    user = User(
        email=payload.email,
        name=payload.name,
        oauth_provider=payload.oauth_provider,
        # oauth_id provisório até o membro logar de fato via OAuth.
        oauth_id=f"pending-{payload.email}",
        role=payload.role,
        agency_id=current_agency_id(),
    )
    db.session.add(user)
    db.session.commit()
    return created(_dump(user))


@bp.patch("/<user_id>")
@require_auth
def update_user(user_id):
    target = get_scoped_or_404(User, user_id)
    current = g.current_user

    is_admin = current.role == UserRole.ADMIN
    is_self = current.id == target.id
    if not (is_admin or is_self):
        raise ForbiddenError("Só admin pode editar outros usuários", code="insufficient_role")

    payload = parse_json(UserUpdateIn)
    data = payload.model_dump(exclude_unset=True)

    # Só admin pode mudar role.
    if "role" in data and not is_admin:
        raise ForbiddenError("Só admin pode alterar role", code="insufficient_role")

    for field, value in data.items():
        setattr(target, field, value)
    db.session.commit()
    return ok(_dump(target))


@bp.delete("/<user_id>")
@require_auth
@require_role(UserRole.ADMIN)
def delete_user(user_id):
    target = get_scoped_or_404(User, user_id)
    if target.id == g.current_user.id:
        raise ValidationError("Admin não pode se auto-remover", code="cannot_delete_self")
    target.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return no_content()
