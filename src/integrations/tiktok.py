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
    SocialAdapter,
    raise_for_social_status,
)
from src.models import PostType

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com/v2"
SCOPES = ["user.info.basic", "user.info.stats", "video.list"]
TIMEOUT = 15


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
            params={"fields": "open_id,display_name,follower_count"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        u = r.json().get("data", {}).get("user", {})
        return ProfileMetrics(
            follower_count=int(u.get("follower_count", 0)),
            handle=u.get("display_name"),
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
        out = []
        for v in r.json().get("data", {}).get("videos", []):
            views = int(v.get("view_count", 0))
            out.append(
                NormalizedPost(
                    platform_post_id=str(v["id"]),
                    post_type=PostType.VIDEO,
                    posted_at=_from_unix(v.get("create_time")),
                    caption=v.get("title"),
                    video_url=v.get("share_url"),
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
