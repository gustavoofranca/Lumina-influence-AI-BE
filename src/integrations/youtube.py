"""Adaptador YouTube via YouTube Data API v3 + Analytics API.

Docs: https://developers.google.com/youtube/v3
OAuth: Google OAuth (escopo youtube.readonly, yt-analytics.readonly). Usa as
credenciais do Google (mesmo projeto do login). Não exige App Review da Meta —
é a plataforma mais acessível de habilitar.
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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DATA = "https://www.googleapis.com/youtube/v3"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TIMEOUT = 15


class YouTubeAdapter(SocialAdapter):
    platform = "youtube"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        # YouTube reusa as credenciais Google (com YOUTUBE_* opcional pra separar).
        self._cid = client_id or current_app.config.get("YOUTUBE_CLIENT_ID") or current_app.config.get("GOOGLE_CLIENT_ID")
        self._secret = (
            client_secret
            or current_app.config.get("YOUTUBE_CLIENT_SECRET")
            or current_app.config.get("GOOGLE_CLIENT_SECRET")
        )

    def _require_creds(self):
        if not self._cid or not self._secret:
            raise PlatformNotConfiguredError(
                "Credenciais YouTube/Google ausentes",
                details={"missing": ["YOUTUBE_CLIENT_ID/GOOGLE_CLIENT_ID"]},
            )

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_creds()
        params = {
            "client_id": self._cid,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(SCOPES),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        self._require_creds()
        r = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": self._cid,
                "client_secret": self._secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        d = r.json()
        return OAuthTokenBundle(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token"),
            expires_at=_expires(d.get("expires_in")),
        )

    def refresh(self, refresh_token: str) -> OAuthTokenBundle:
        self._require_creds()
        r = requests.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._cid,
                "client_secret": self._secret,
                "grant_type": "refresh_token",
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        d = r.json()
        return OAuthTokenBundle(
            access_token=d["access_token"],
            refresh_token=refresh_token,
            expires_at=_expires(d.get("expires_in")),
        )

    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics:
        r = requests.get(
            f"{DATA}/channels",
            params={"part": "snippet,statistics", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        items = r.json().get("items", [])
        if not items:
            return ProfileMetrics(follower_count=0)
        ch = items[0]
        return ProfileMetrics(
            follower_count=int(ch.get("statistics", {}).get("subscriberCount", 0)),
            handle=ch.get("snippet", {}).get("title"),
            platform_user_id=ch.get("id"),
        )

    def fetch_recent_posts(self, access_token: str, limit: int = 10) -> list[NormalizedPost]:
        headers = {"Authorization": f"Bearer {access_token}"}
        # 1) IDs dos vídeos mais recentes do canal
        s = requests.get(
            f"{DATA}/search",
            params={"part": "id", "forMine": "true", "type": "video",
                    "order": "date", "maxResults": limit},
            headers=headers, timeout=TIMEOUT,
        )
        raise_for_social_status(s, platform=self.platform)
        ids = [it["id"]["videoId"] for it in s.json().get("items", []) if it.get("id", {}).get("videoId")]
        if not ids:
            return []
        # 2) Estatísticas dos vídeos
        v = requests.get(
            f"{DATA}/videos",
            params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)},
            headers=headers, timeout=TIMEOUT,
        )
        raise_for_social_status(v, platform=self.platform)
        out = []
        for item in v.json().get("items", []):
            stats = item.get("statistics", {})
            snip = item.get("snippet", {})
            views = int(stats.get("viewCount", 0))
            out.append(
                NormalizedPost(
                    platform_post_id=item["id"],
                    post_type=PostType.VIDEO,
                    posted_at=_parse_iso(snip.get("publishedAt")),
                    caption=snip.get("title"),
                    video_url=f"https://youtube.com/watch?v={item['id']}",
                    thumbnail_url=(snip.get("thumbnails", {}).get("high", {}) or {}).get("url"),
                    reach_total=views,
                    # viewCount é o total de exibições e não separa origem paga:
                    # isso exigiria cruzar com Google Ads, atrás de conta
                    # comercial. As colunas são NOT NULL, então a divisão fica em
                    # orgânico=total e pago=0 por decisão registrada na ADR-005,
                    # que também obriga a declarar o limite ao apresentar o dado.
                    reach_organic=views,
                    reach_paid=0,
                    impressions=views,
                    likes=int(stats.get("likeCount", 0)),
                    comments_count=int(stats.get("commentCount", 0)),
                    # A Data API v3 não expõe compartilhamento nem salvamento.
                    shares=0,
                    saves=0,
                )
            )
        return out

    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict:
        # Reach orgânico/pago detalhado viria da YouTube Analytics API (relatórios).
        return {}

    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]:
        r = requests.get(
            f"{DATA}/commentThreads",
            params={"part": "snippet", "videoId": platform_post_id, "maxResults": limit},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        out = []
        for thread in r.json().get("items", []):
            top = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            out.append(
                NormalizedComment(
                    platform_comment_id=thread["id"],
                    content=top.get("textDisplay", ""),
                    author_handle=top.get("authorDisplayName"),
                    posted_at=_parse_iso(top.get("publishedAt")),
                    like_count=int(top.get("likeCount", 0)),
                )
            )
        return out


def _expires(expires_in) -> datetime | None:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
