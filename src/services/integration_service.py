"""Orquestra OAuth das redes sociais + coleta/sync de métricas.

- State CSRF: JWT curto assinado (carrega influencer_id, platform, agency_id).
- Tokens persistidos sempre criptografados (Fernet) em SocialAccount.
- sync: usa a API real se há token; senão simula (modo dev) reaproveitando crescimento.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app
from sqlalchemy import select

from src.extensions import db
from src.integrations.base import (
    NormalizedComment,
    NormalizedPost,
    OAuthTokenBundle,
    RateLimitError,
    SocialAdapter,
    TokenRevokedError,
)
from src.integrations.instagram import InstagramAdapter
from src.integrations.tiktok import TikTokAdapter
from src.integrations.youtube import YouTubeAdapter
from src.models import (Comment, Influencer, OAuthProvider, OAuthState, Platform,
                        Post, SocialAccount)
from src.utils.crypto import decrypt_token, encrypt_token
from src.utils.errors import NotFoundError, UnauthorizedError, ValidationError

logger = logging.getLogger(__name__)

STATE_TTL = timedelta(minutes=15)
SOCIAL_STATE_TYPE = "social_oauth_state"

_ADAPTERS = {
    Platform.INSTAGRAM: InstagramAdapter,
    Platform.TIKTOK: TikTokAdapter,
    Platform.YOUTUBE: YouTubeAdapter,
}

# Provedor OAuth de cada plataforma, para registrar o nonce do state na tabela
# `oauth_states` — a mesma que o login usa para garantir uso único. O enum
# `oauth_provider` só conhece google e microsoft: o YouTube cabe porque seu
# provedor é literalmente accounts.google.com. Instagram e TikTok exigiriam
# ampliar o enum, o que é migration; até lá ficam de fora do mapa e o
# consumo do nonce falha fechado, em vez de seguir sem garantia.
_STATE_NONCE_PROVIDER = {
    Platform.YOUTUBE: OAuthProvider.GOOGLE,
}


# ==========================================================================
# Registry
# ==========================================================================
def get_adapter(platform: Platform) -> SocialAdapter:
    cls = _ADAPTERS.get(platform)
    if cls is None:
        raise ValidationError(f"Plataforma não suportada: {platform}")
    return cls()


def parse_platform(raw: str) -> Platform:
    try:
        return Platform(raw)
    except ValueError as exc:
        raise NotFoundError(f"Plataforma desconhecida: {raw}", code="unknown_platform") from exc


# ==========================================================================
# State assinado (CSRF)
# ==========================================================================
def mint_state(*, influencer_id: uuid.UUID, platform: Platform, agency_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "typ": SOCIAL_STATE_TYPE,
        "inf": str(influencer_id),
        "plat": platform.value,
        "ag": str(agency_id),
        "iat": int(now.timestamp()),
        "exp": int((now + STATE_TTL).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def verify_state(state: str, *, expected_platform: Platform) -> dict:
    try:
        payload = jwt.decode(state, current_app.config["JWT_SECRET"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("OAuth state expirado", code="oauth_state_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("OAuth state inválido", code="oauth_state_invalid") from exc
    if payload.get("typ") != SOCIAL_STATE_TYPE:
        raise UnauthorizedError("OAuth state de tipo errado", code="oauth_state_invalid")
    if payload.get("plat") != expected_platform.value:
        raise UnauthorizedError("OAuth state de plataforma divergente", code="oauth_state_invalid")
    return payload


# ==========================================================================
# Connect / Callback
# ==========================================================================
def build_connect_url(
    *, influencer: Influencer, platform: Platform, agency_id: uuid.UUID, redirect_uri: str
) -> str:
    adapter = get_adapter(platform)
    state = mint_state(influencer_id=influencer.id, platform=platform, agency_id=agency_id)
    return adapter.build_auth_url(state=state, redirect_uri=redirect_uri)


def consume_state_nonce(payload: dict, platform: Platform) -> None:
    """Gasta o `jti` do state, tornando-o de uso único.

    O callback não é autenticado — quem chega nele é o browser vindo do
    provedor, sem Bearer. A garantia de que aquele state vale uma vez só é o
    que substitui a sessão: sem isso, um state vazado dentro dos 15 minutos
    poderia ser reapresentado. Espelha o `consume_oauth_state` do login.
    """
    provider = _STATE_NONCE_PROVIDER.get(platform)
    if provider is None:
        raise ValidationError(
            f"Uso único de state ainda não suportado para {platform.value}",
            details={"motivo": "enum oauth_provider precisa ser ampliado (migration)"},
        )

    jti = payload.get("jti")
    if not jti:
        raise UnauthorizedError("OAuth state sem identificador", code="oauth_state_invalid")

    ja_usado = db.session.scalar(
        select(OAuthState).where(OAuthState.state_token == jti)
    )
    if ja_usado is not None:
        raise UnauthorizedError("OAuth state já utilizado", code="oauth_state_replayed")

    db.session.add(OAuthState(
        provider=provider,
        state_token=jti,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    ))
    db.session.commit()


def handle_callback(
    *, platform: Platform, code: str, state: str, redirect_uri: str
) -> SocialAccount:
    """Conclui o OAuth a partir do state assinado, sem depender de sessão.

    A agência sai do próprio state — ele é assinado com o JWT_SECRET e só é
    emitido em /connect, que exige ADMIN ou MEMBER e resolve o influencer no
    escopo de quem pediu. O influencer precisa continuar pertencendo àquela
    agência agora, e não só quando o fluxo começou.
    """
    payload = verify_state(state, expected_platform=platform)
    consume_state_nonce(payload, platform)

    agency_id = uuid.UUID(payload["ag"])
    influencer_id = uuid.UUID(payload["inf"])
    influencer = db.session.scalar(
        select(Influencer).where(
            Influencer.id == influencer_id, Influencer.agency_id == agency_id
        )
    )
    if influencer is None:
        raise NotFoundError("Influencer não encontrado")

    adapter = get_adapter(platform)
    bundle: OAuthTokenBundle = adapter.exchange_code(code=code, redirect_uri=redirect_uri)
    profile = adapter.fetch_profile_metrics(bundle.access_token)

    handle = bundle.handle or profile.handle or f"{platform.value}_user"
    platform_user_id = bundle.platform_user_id or profile.platform_user_id

    # Upsert por (influencer, platform, handle)
    account = db.session.scalar(
        select(SocialAccount).where(
            SocialAccount.influencer_id == influencer_id,
            SocialAccount.platform == platform,
            SocialAccount.handle == handle,
        )
    )
    if account is None:
        account = SocialAccount(
            influencer_id=influencer_id, platform=platform, handle=handle
        )
        db.session.add(account)

    account.platform_user_id = platform_user_id
    account.follower_count = profile.follower_count or account.follower_count or 0
    account.access_token_encrypted = encrypt_token(bundle.access_token)
    account.refresh_token_encrypted = encrypt_token(bundle.refresh_token)
    account.token_expires_at = bundle.expires_at
    account.last_synced_at = None
    db.session.commit()
    logger.info("Conta social conectada: influencer=%s platform=%s", influencer_id, platform.value)
    return account


def disconnect_account(*, social_account_id: uuid.UUID, agency_id: uuid.UUID) -> None:
    account = db.session.scalar(
        select(SocialAccount)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(SocialAccount.id == social_account_id, Influencer.agency_id == agency_id)
    )
    if account is None:
        raise NotFoundError("SocialAccount não encontrada")
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    db.session.commit()


# ==========================================================================
# Sync
# ==========================================================================
def _valid_access_token(account: SocialAccount, adapter: SocialAdapter) -> str | None:
    """Decifra o token; se expirado e há refresh, renova e repersiste. None se não conectada."""
    if not account.access_token_encrypted:
        return None
    access = decrypt_token(account.access_token_encrypted)

    expired = (
        account.token_expires_at is not None
        and _as_aware(account.token_expires_at) <= datetime.now(timezone.utc)
    )
    if expired and account.refresh_token_encrypted:
        refresh = decrypt_token(account.refresh_token_encrypted)
        bundle = adapter.refresh(refresh)
        account.access_token_encrypted = encrypt_token(bundle.access_token)
        if bundle.refresh_token:
            account.refresh_token_encrypted = encrypt_token(bundle.refresh_token)
        account.token_expires_at = bundle.expires_at
        db.session.commit()
        return bundle.access_token
    return access


def sync_influencer(
    influencer: Influencer, *, adapter_factory=None, simulate_if_no_token: bool = True
) -> dict:
    """Sincroniza todas as contas do influencer. Retorna resumo por conta.

    adapter_factory=None usa `get_adapter` resolvido em runtime (permite monkeypatch).
    """
    factory = adapter_factory or get_adapter
    results = []
    for account in influencer.social_accounts:
        adapter = factory(account.platform)
        try:
            token = _valid_access_token(account, adapter)
            if token is None:
                if not simulate_if_no_token:
                    r = {"status": "not_connected"}
                else:
                    r = _simulate_sync(account)
            else:
                r = _real_sync(account, adapter, token)
        except TokenRevokedError:
            # Token revogado pelo usuário na plataforma — limpa pra forçar reconexão.
            db.session.rollback()
            account.access_token_encrypted = None
            account.refresh_token_encrypted = None
            r = {"status": "token_revoked"}
        except RateLimitError:
            db.session.rollback()
            r = {"status": "rate_limited"}
        results.append({"platform": account.platform.value, **r})

    db.session.commit()
    return {"influencer_id": str(influencer.id), "accounts": results}


def _real_sync(account: SocialAccount, adapter: SocialAdapter, token: str) -> dict:
    posts = adapter.fetch_recent_posts(token, limit=10)
    created, updated = 0, 0
    for np in posts:
        existing = db.session.scalar(
            select(Post).where(
                Post.social_account_id == account.id,
                Post.platform_post_id == np.platform_post_id,
            )
        )
        if existing is None:
            post = _post_from_normalized(account.id, np)
            db.session.add(post)
            db.session.flush()
            created += 1
            _ingest_comments(adapter, token, post, np.platform_post_id)
        else:
            _apply_metrics(existing, np)
            updated += 1

    account.last_synced_at = datetime.now(timezone.utc)
    return {"status": "synced", "mode": "real", "posts_created": created, "posts_updated": updated}


def _simulate_sync(account: SocialAccount, *, rng: random.Random | None = None) -> dict:
    """Modo dev: cresce métricas dos posts existentes da conta (sem API real)."""
    rng = rng or random.Random()
    posts = db.session.scalars(
        select(Post).where(Post.social_account_id == account.id)
    ).all()
    for p in posts:
        growth = 1 + rng.uniform(0.005, 0.05)
        p.likes = int(p.likes * growth)
        p.reach_organic = int(p.reach_organic * growth)
        p.reach_paid = int(p.reach_paid * growth)
        p.reach_total = p.reach_organic + p.reach_paid
        p.impressions = int(p.impressions * growth)
    account.last_synced_at = datetime.now(timezone.utc)
    return {"status": "simulated", "mode": "simulated", "posts_updated": len(posts)}


def _ingest_comments(adapter, token, post: Post, platform_post_id: str) -> None:
    try:
        comments: list[NormalizedComment] = adapter.fetch_post_comments(
            token, platform_post_id, limit=15
        )
    except Exception as exc:  # comentários são best-effort
        logger.debug("Falha ao buscar comentários (%s): %s", platform_post_id, exc)
        return
    for nc in comments:
        db.session.add(
            Comment(
                post_id=post.id,
                platform_comment_id=nc.platform_comment_id,
                content=nc.content,
                author_handle=nc.author_handle,
                posted_at=nc.posted_at,
                like_count=nc.like_count,
            )
        )


def _post_from_normalized(account_id: uuid.UUID, np: NormalizedPost) -> Post:
    return Post(
        social_account_id=account_id,
        platform_post_id=np.platform_post_id,
        post_type=np.post_type,
        posted_at=np.posted_at,
        caption=np.caption,
        video_url=np.video_url,
        thumbnail_url=np.thumbnail_url,
        reach_total=np.reach_total,
        reach_organic=np.reach_organic,
        reach_paid=np.reach_paid,
        impressions=np.impressions,
        likes=np.likes,
        comments_count=np.comments_count,
        shares=np.shares,
        saves=np.saves,
        avg_watch_time=np.avg_watch_time,
        retention_rate=np.retention_rate,
        needs_analysis=True,  # post novo entra na fila de análise (B7)
    )


def _apply_metrics(post: Post, np: NormalizedPost) -> None:
    post.reach_total = np.reach_total
    post.reach_organic = np.reach_organic
    post.reach_paid = np.reach_paid
    post.impressions = np.impressions
    post.likes = np.likes
    post.comments_count = np.comments_count
    post.shares = np.shares
    post.saves = np.saves


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
