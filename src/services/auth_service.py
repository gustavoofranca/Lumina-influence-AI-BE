"""Serviço de autenticação — orquestra OAuth + emissão de JWT + criação de Agency.

Regras de negócio principais:
- Se já existe User com aquele email: faz login (atualiza oauth_id/provider/avatar pra refletir
  o que veio do provider, importante pro caso em que o seed colocou um fake oauth_id).
- Se não existe: cria nova Agency "Minha Agência" (sem plano), atribui User como ADMIN.
- OAuth state (anti-CSRF) é persistido em OAuthStates com expiração de 15 min.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.extensions import db
from src.models import (
    Agency,
    OAuthProvider,
    OAuthState,
    User,
    UserRole,
)
from src.utils.errors import UnauthorizedError

logger = logging.getLogger(__name__)

STATE_TTL = timedelta(minutes=15)
DEFAULT_AGENCY_NAME = "Minha Agência"


# --------------------------------------------------------------------------
# OAuth state (CSRF)
# --------------------------------------------------------------------------
def create_oauth_state(provider: OAuthProvider, code_verifier: str | None = None) -> str:
    """Gera state aleatório, persiste em OAuthStates, retorna o token."""
    state_token = secrets.token_urlsafe(32)
    record = OAuthState(
        user_id=None,
        provider=provider,
        state_token=state_token,
        code_verifier=code_verifier,
        expires_at=datetime.now(timezone.utc) + STATE_TTL,
    )
    db.session.add(record)
    db.session.commit()
    return state_token


def consume_oauth_state(provider: OAuthProvider, state_token: str) -> OAuthState:
    """Valida e remove o state. Levanta UnauthorizedError se inválido/expirado."""
    record = db.session.scalar(
        select(OAuthState).where(
            OAuthState.state_token == state_token,
            OAuthState.provider == provider,
        )
    )
    if record is None:
        raise UnauthorizedError("OAuth state inválido", code="oauth_state_invalid")
    # SQLite (testes) descarta tzinfo — assume UTC pra comparar com aware.
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        db.session.delete(record)
        db.session.commit()
        raise UnauthorizedError("OAuth state expirado", code="oauth_state_expired")
    db.session.delete(record)
    db.session.commit()
    return record


# --------------------------------------------------------------------------
# find_or_create_user
# --------------------------------------------------------------------------
def find_or_create_user_from_oauth(
    *,
    provider: OAuthProvider,
    oauth_id: str,
    email: str,
    name: str,
    avatar_url: str | None = None,
) -> User:
    """Localiza usuário por email; cria agência+admin se for primeira vez.

    Política decidida na B3:
    - Email já existe (pode ser do seed da B2 ou login anterior) → atualiza oauth_id real
      e avatar, mantém agência. Não troca provider se já estava setado pra outro.
    - Email novo → cria nova Agency "Minha Agência" + User como ADMIN.
    """
    user = db.session.scalar(select(User).where(User.email == email))

    if user is not None:
        if user.deleted_at is not None:
            raise UnauthorizedError("Usuário desativado", code="user_disabled")

        # Sincroniza identidade real do provider (substitui valores fake do seed).
        user.oauth_id = oauth_id
        user.oauth_provider = provider
        if avatar_url:
            user.avatar_url = avatar_url
        if not user.name:
            user.name = name
        db.session.commit()
        logger.info("Login: usuário existente %s via %s", user.email, provider.value)
        return user

    # Email novo → cria agência + user admin
    agency = Agency(name=DEFAULT_AGENCY_NAME, plan=None)
    user = User(
        email=email,
        name=name,
        avatar_url=avatar_url,
        oauth_provider=provider,
        oauth_id=oauth_id,
        role=UserRole.ADMIN,
        agency=agency,
    )
    db.session.add(agency)
    db.session.add(user)
    db.session.commit()
    logger.info("Signup: novo usuário %s + agência %s", user.email, agency.id)
    return user


# --------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------
def cleanup_expired_oauth_states() -> int:
    """Remove states expirados. Usado por job cron no B7."""
    now = datetime.now(timezone.utc)
    count = (
        db.session.query(OAuthState)
        .filter(OAuthState.expires_at < now)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return count


def resolve_dev_login_user(email: str | None) -> User | None:
    """Usuário para o dev-login.

    Com email, busca aquele. Sem email, prefere o admin da agência seedada —
    é o que dá um ambiente reconhecível ao abrir o app — e cai em qualquer
    admin se o seed não estiver carregado.
    """
    if email:
        return db.session.scalar(select(User).where(User.email == email))

    seeded_admin = db.session.scalar(
        select(User)
        .where(User.role == UserRole.ADMIN, User.email.like("%lumina-agency%"))
        .order_by(User.created_at.asc())
    )
    if seeded_admin is not None:
        return seeded_admin
    return db.session.scalar(select(User).where(User.role == UserRole.ADMIN))
