"""Blueprint /api/v1/users — gestão de membros da própria agência."""
from __future__ import annotations

from flask import Blueprint, g

from src.models import User, UserRole
from src.schemas.user import UserCreateIn, UserOut, UserUpdateIn
from src.services import user_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import ForbiddenError, ValidationError
from src.utils.pagination import paginate
from src.utils.responses import created, no_content, ok, paginated
from src.utils.validation import parse_json

bp = Blueprint("users", __name__, url_prefix="/api/v1/users")


def _dump(user: User) -> dict:
    return UserOut.model_validate(user).model_dump(mode="json")


@bp.get("")
@require_auth
def list_users():
    page = paginate(user_service.build_user_query(current_agency_id()))
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
    user = user_service.create_member(
        email=payload.email,
        name=payload.name,
        role=payload.role,
        oauth_provider=payload.oauth_provider,
        agency_id=current_agency_id(),
    )
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

    return ok(_dump(user_service.apply_update(target, data)))


@bp.get("/me/deletion-preview")
@require_auth
def preview_own_deletion():
    """O que a exclusão da própria conta levaria junto.

    A interface precisa dizer isto **antes** de pedir a confirmação: avisar
    "isto apaga a agência" depois do fato não é aviso, é notificação.
    """
    return ok(user_service.preview_own_deletion(g.current_user))


@bp.delete("/me")
@require_auth
def delete_own_account():
    """Exclusão definitiva pedida pelo próprio titular.

    Rota separada de `DELETE /<user_id>` de propósito: aquela é remoção de
    membro **por um admin**, é soft delete e proíbe auto-remoção. Esta é o
    direito de eliminação do titular (LGPD, art. 18, VI) e apaga de verdade.
    """
    return ok(user_service.erase_own_account(g.current_user))


@bp.delete("/<user_id>")
@require_auth
@require_role(UserRole.ADMIN)
def delete_user(user_id):
    target = get_scoped_or_404(User, user_id)
    if target.id == g.current_user.id:
        raise ValidationError("Admin não pode se auto-remover", code="cannot_delete_self")
    user_service.soft_delete(target)
    return no_content()
