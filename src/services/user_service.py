"""Gestão de membros da agência."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, select

from src.extensions import db
from src.models import OAuthProvider, User, UserRole
from src.utils.errors import ConflictError


def build_user_query(agency_id: uuid.UUID) -> Select:
    """SELECT dos membros ativos da agência, em ordem alfabética."""
    return (
        select(User)
        .where(User.agency_id == agency_id, User.deleted_at.is_(None))
        .order_by(User.name.asc())
    )


def find_by_email(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email))


def find_first_by_role(role: UserRole) -> User | None:
    return db.session.scalar(select(User).where(User.role == role))


def create_member(
    *,
    email: str,
    name: str,
    role: UserRole,
    oauth_provider: OAuthProvider,
    agency_id: uuid.UUID,
) -> User:
    """Cria o membro. E-mail é único na base inteira, não só na agência."""
    if find_by_email(email) is not None:
        raise ConflictError("Email já cadastrado", details={"email": email})

    user = User(
        email=email,
        name=name,
        oauth_provider=oauth_provider,
        # oauth_id provisório até o membro logar de fato via OAuth.
        oauth_id=f"pending-{email}",
        role=role,
        agency_id=agency_id,
    )
    db.session.add(user)
    db.session.commit()
    return user


def apply_update(user: User, data: dict) -> User:
    for field, value in data.items():
        setattr(user, field, value)
    db.session.commit()
    return user


def soft_delete(user: User) -> None:
    user.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
