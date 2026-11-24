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

from flask import current_app
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Agency,
    FinalidadeToken,
    OAuthProvider,
    OAuthState,
    User,
    UserRole,
)
from src.schemas.auth import AgencySummaryOut, LoginCallbackOut, TokenPairOut, UserOut
from src.services import token_service
from src.utils.errors import UnauthorizedError
from src.utils.jwt_utils import issue_token_pair

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
) -> tuple[User, bool]:
    """Localiza usuário por email; cria agência+admin se for primeira vez.

    Devolve `(usuário, agência_criada)`. O segundo item diz se este login
    acabou de criar uma agência — é o que permite ao front pedir o nome dela em
    vez de deixar o placeholder para sempre.

    Política decidida na B3:
    - Email já existe (pode ser do seed da B2 ou login anterior) → atualiza oauth_id real
      e avatar, mantém agência. Não troca provider se já estava setado pra outro.
    - Email novo → cria nova Agency "Minha Agência" + User como ADMIN.
    """
    email = email.strip().lower()
    user = db.session.scalar(select(User).where(func.lower(User.email) == email))

    if (
        user is not None
        and user.password_hash
        and user.email_verificado_em is None
        and user.deleted_at is None
    ):
        # Pré-sequestro de conta: alguém cadastrou este e-mail com uma senha que
        # só ele sabe e nunca confirmou o link. O provedor acabou de provar quem
        # é a dona do endereço; herdar aquele cadastro entregaria a ela uma conta
        # cuja senha o outro conhece. O cadastro pendente não tem dado nenhum —
        # não dá para entrar sem confirmar —, então some, e a conta nasce limpa.
        agencia = user.agency
        sozinho = agencia is not None and all(u.id == user.id for u in agencia.users)
        logger.info("OAuth descartou cadastro não verificado %s", user.id)
        db.session.delete(agencia if sozinho else user)
        db.session.flush()
        user = None

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
        # O provedor confirmou o e-mail: vale como verificação.
        if user.email_verificado_em is None:
            user.email_verificado_em = datetime.now(timezone.utc)
        db.session.commit()
        # O log identifica pelo id, não pelo email. Email é dado pessoal sob a
        # LGPD, e o log sai da fronteira de retenção do banco: vai para arquivo,
        # para o agregador e para o backup, onde a exclusão de conta não alcança.
        # O id resolve o mesmo diagnóstico e não carrega identificação direta.
        logger.info("Login: usuário existente %s via %s", user.id, provider.value)
        return user, False

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
        email_verificado_em=datetime.now(timezone.utc),
    )
    db.session.add(agency)
    db.session.add(user)
    db.session.commit()
    logger.info("Signup: novo usuário %s + agência %s", user.id, agency.id)
    return user, True


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


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
def _precisa_ativar_2fa(user: User) -> bool:
    return user.role == UserRole.ADMIN and current_app.config.get("MFA_OBRIGATORIO_PARA_ADMIN", True)


def concluir_login(user: User, *, exigir_2fa: bool = True) -> dict:
    """Ponto único em que um login vira sessão: senha, Google, Microsoft,
    verificação de e-mail, troca de senha e o atalho de desenvolvimento passam
    todos por aqui.

    Com `exigir_2fa`, quem tem 2FA recebe um ticket de desafio e o
    administrador sem 2FA recebe um ticket de ativação — nenhum dos dois é
    sessão (spec de 19/10/2026). `exigir_2fa=False` é para quem já cumpriu o
    segundo fator nesta mesma requisição, ou já estava numa sessão, e para o
    atalho de desenvolvimento.
    """
    if exigir_2fa and user.mfa_enabled:
        return {"mfa": "challenge", "mfa_ticket": token_service.emitir(user, FinalidadeToken.DESAFIO_2FA)}
    if exigir_2fa and _precisa_ativar_2fa(user):
        return {"mfa": "setup", "mfa_ticket": token_service.emitir(user, FinalidadeToken.ATIVAR_2FA)}
    tokens = issue_token_pair(user)
    ttl = int(current_app.config["JWT_ACCESS_TTL"].total_seconds())
    return LoginCallbackOut(
        user=UserOut.model_validate(user),
        agency=AgencySummaryOut.model_validate(user.agency) if user.agency else None,
        tokens=TokenPairOut(**tokens, expires_in_seconds=ttl),
    ).model_dump(mode="json")


def invalidar_sessoes(user: User) -> None:
    """Todo token emitido antes deste segundo deixa de valer. O commit fica com quem chama.

    Truncado no segundo porque o `iat` do JWT é inteiro: o par emitido logo em
    seguida, no mesmo segundo, continua válido — é o da sessão que acabou de
    trocar a senha.
    """
    user.sessoes_validas_desde = datetime.now(timezone.utc).replace(microsecond=0)
