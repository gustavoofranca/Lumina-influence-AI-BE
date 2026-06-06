"""Interface comum dos adaptadores de plataformas sociais + tipos normalizados.

Cada plataforma (Instagram/Meta, TikTok, YouTube) implementa `SocialAdapter`
mapeando suas respostas pra estes dataclasses normalizados, que o restante do
sistema consome sem conhecer detalhes de cada API.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime

from src.models import PostType
from src.utils.errors import LuminaError


# ==========================================================================
# Erros tipados (mapeiam pra HTTP no error handler global)
# ==========================================================================
class SocialApiError(LuminaError):
    status_code = 502
    code = "social_api_error"


class PlatformNotConfiguredError(SocialApiError):
    status_code = 503
    code = "platform_not_configured"


class RateLimitError(SocialApiError):
    status_code = 429
    code = "platform_rate_limited"


class TokenRevokedError(SocialApiError):
    status_code = 401
    code = "platform_token_revoked"


class PrivateAccountError(SocialApiError):
    status_code = 403
    code = "platform_account_private"


def raise_for_social_status(resp, *, platform: str) -> None:
    """Mapeia status HTTP comuns das APIs sociais pra erros tipados."""
    if resp.status_code == 200:
        return
    body = resp.text[:400]
    if resp.status_code == 429:
        raise RateLimitError(f"{platform}: rate limit (429)", details={"body": body})
    if resp.status_code == 401:
        raise TokenRevokedError(f"{platform}: token revogado/expirado (401)", details={"body": body})
    if resp.status_code == 403:
        raise PrivateAccountError(f"{platform}: acesso negado (403)", details={"body": body})
    raise SocialApiError(
        f"{platform}: erro {resp.status_code}",
        details={"status": resp.status_code, "body": body},
    )


# ==========================================================================
# Tipos normalizados
# ==========================================================================
@dataclass
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    platform_user_id: str | None = None
    handle: str | None = None
    follower_count: int | None = None


@dataclass
class ProfileMetrics:
    follower_count: int
    handle: str | None = None
    platform_user_id: str | None = None


@dataclass
class NormalizedPost:
    platform_post_id: str
    post_type: PostType
    posted_at: datetime
    caption: str | None = None
    video_url: str | None = None
    thumbnail_url: str | None = None
    reach_total: int = 0
    reach_organic: int = 0
    reach_paid: int = 0
    impressions: int = 0
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    saves: int = 0
    avg_watch_time: float | None = None
    retention_rate: float | None = None


@dataclass
class NormalizedComment:
    platform_comment_id: str
    content: str
    posted_at: datetime
    author_handle: str | None = None
    like_count: int = 0


# ==========================================================================
# Interface
# ==========================================================================
class SocialAdapter(abc.ABC):
    """Contrato que cada plataforma implementa."""

    platform: str

    @abc.abstractmethod
    def build_auth_url(self, *, state: str, redirect_uri: str) -> str: ...

    @abc.abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle: ...

    @abc.abstractmethod
    def refresh(self, refresh_token: str) -> OAuthTokenBundle: ...

    @abc.abstractmethod
    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics: ...

    @abc.abstractmethod
    def fetch_recent_posts(self, access_token: str, limit: int = 10) -> list[NormalizedPost]: ...

    @abc.abstractmethod
    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict: ...

    @abc.abstractmethod
    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]: ...
