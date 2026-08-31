"""Adaptador TikTok via TikTok for Developers (Display + Business API).

Docs: https://developers.tiktok.com/doc/
OAuth: client_key/client_secret, escopos user.info.basic, video.list.
Estrutura fiel à API; validável só com app aprovado. Totalmente mockável.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from flask import current_app

from src.integrations.base import (
    NormalizedComment,
    NormalizedPost,
    OAuthTokenBundle,
    PlatformNotConfiguredError,
    ProfileMetrics,
    RateLimitError,
    SocialAdapter,
    SocialApiError,
    TokenRevokedError,
    raise_for_social_status,
)
from src.models import PostType

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com/v2"
SCOPES = ["user.info.basic", "user.info.stats", "video.list"]
TIMEOUT = 15

# O TikTok responde **200 mesmo quando falha**: o corpo sempre traz um objeto
# `error`, e `code == "ok"` é o único valor que significa sucesso. Conferir só o
# status HTTP deixa a falha passar como resposta vazia — token revogado viraria
# "criador sem post", que é o defeito que a ADR-003 proíbe.
ERRO_OK = "ok"
_ERROS_DE_TOKEN = ("access_token_invalid", "invalid_token", "token_expired")
_ERROS_DE_ESCOPO = ("scope_not_authorized", "scope_permission_missed", "invalid_scope")
_ERROS_DE_COTA = ("rate_limit_exceeded", "daily_quota_limit_exceeded")


def _raise_for_tiktok_error(payload: dict) -> None:
    """Traduz o objeto `error` do corpo em exceção tipada."""
    erro = payload.get("error") or {}
    codigo = erro.get("code")
    # Ausência do objeto é resposta de formato inesperado, não sucesso: só
    # `code == "ok"` autoriza seguir.
    if codigo == ERRO_OK:
        return
    detalhes = {"code": codigo, "message": str(erro.get("message", ""))[:200]}
    if codigo in _ERROS_DE_TOKEN:
        raise TokenRevokedError("tiktok: autorização expirada ou revogada", details=detalhes)
    if codigo in _ERROS_DE_COTA:
        raise RateLimitError("tiktok: limite de requisições atingido", details=detalhes)
    if codigo in _ERROS_DE_ESCOPO:
        raise PlatformNotConfiguredError("tiktok: escopo não autorizado", details=detalhes)
    raise SocialApiError(f"tiktok: erro {codigo}", details=detalhes)


class TikTokAdapter(SocialAdapter):
    platform = "tiktok"

    def __init__(self, client_key: str | None = None, client_secret: str | None = None):
        self._key = client_key or current_app.config.get("TIKTOK_CLIENT_KEY")
        self._secret = client_secret or current_app.config.get("TIKTOK_CLIENT_SECRET")

    def _require_creds(self):
        if not self._key or not self._secret:
            raise PlatformNotConfiguredError(
                "Credenciais TikTok ausentes",
                details={"missing": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"]},
            )

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_creds()
        params = {
            "client_key": self._key,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(SCOPES),
            "response_type": "code",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        self._require_creds()
        r = requests.post(
            TOKEN_URL,
            data={
                "client_key": self._key,
                "client_secret": self._secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        d = r.json()
        return OAuthTokenBundle(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token"),
            expires_at=_expires(d.get("expires_in")),
            platform_user_id=d.get("open_id"),
        )

    def refresh(self, refresh_token: str) -> OAuthTokenBundle:
        self._require_creds()
        r = requests.post(
            TOKEN_URL,
            data={
                "client_key": self._key,
                "client_secret": self._secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        d = r.json()
        return OAuthTokenBundle(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token", refresh_token),
            expires_at=_expires(d.get("expires_in")),
        )

    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics:
        r = requests.get(
            f"{API}/user/info/",
            params={"fields": "open_id,username,display_name,follower_count"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        corpo = r.json()
        _raise_for_tiktok_error(corpo)
        u = corpo.get("data", {}).get("user", {})
        return ProfileMetrics(
            follower_count=int(u.get("follower_count", 0)),
            # `username` é o @ do perfil; `display_name` é o nome livre, que o
            # criador troca quando quer. O handle entra na chave única
            # (influencer, plataforma, handle), então usar o nome de exibição
            # faria uma troca de nome nascer como conta duplicada.
            handle=u.get("username") or u.get("display_name"),
            platform_user_id=u.get("open_id"),
        )

    def fetch_recent_posts(self, access_token: str, limit: int = 10) -> list[NormalizedPost]:
        r = requests.post(
            f"{API}/video/list/",
            params={"fields": "id,title,create_time,cover_image_url,share_url,view_count,"
                    "like_count,comment_count,share_count"},
            json={"max_count": limit},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        corpo = r.json()
        _raise_for_tiktok_error(corpo)
        out = []
        for v in corpo.get("data", {}).get("videos", []):
            views = int(v.get("view_count", 0))
            out.append(
                NormalizedPost(
                    platform_post_id=str(v["id"]),
                    post_type=PostType.VIDEO,
                    posted_at=_from_unix(v.get("create_time")),
                    caption=v.get("title"),
                    # `share_url` é a **página** do TikTok, não o arquivo. Baixá-la
                    # entregaria HTML ao analisador multimodal, que o trataria
                    # como vídeo. A Display API não expõe arquivo baixável, então
                    # o campo fica nulo e a análise de vídeo recusa em voz alta.
                    video_url=None,
                    thumbnail_url=v.get("cover_image_url"),
                    reach_total=views,
                    reach_organic=views,
                    reach_paid=0,
                    impressions=views,
                    likes=int(v.get("like_count", 0)),
                    comments_count=int(v.get("comment_count", 0)),
                    shares=int(v.get("share_count", 0)),
                    saves=0,
                )
            )
        return out

    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict:
        # TikTok retorna métricas já no video/list; insights detalhados exigem Business API.
        return {}

    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]:
        # Comentários exigem TikTok Business API + permissão dedicada.
        return []


def _expires(expires_in) -> datetime | None:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))


def _from_unix(ts) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)
