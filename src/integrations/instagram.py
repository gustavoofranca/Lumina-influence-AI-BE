"""Adaptador Instagram via Meta Graph API.

Docs: https://developers.facebook.com/docs/instagram-api
OAuth: Facebook Login (escopos instagram_basic, instagram_manage_insights).
Requer App Review aprovado pra produção; em dev funciona com contas testers.

Os métodos HTTP são fiéis à estrutura da Graph API, mas só podem ser validados
com um app aprovado — por isso são totalmente mockáveis nos testes.
"""
from __future__ import annotations

from datetime import datetime, timezone
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

GRAPH = "https://graph.facebook.com/v21.0"
AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
SCOPES = ["instagram_basic", "instagram_manage_insights", "pages_show_list"]
TIMEOUT = 15


class InstagramAdapter(SocialAdapter):
    platform = "instagram"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self._cid = client_id or current_app.config.get("META_CLIENT_ID")
        self._secret = client_secret or current_app.config.get("META_CLIENT_SECRET")

    def _require_creds(self):
        if not self._cid or not self._secret:
            raise PlatformNotConfiguredError(
                "Credenciais Meta ausentes",
                details={"missing": ["META_CLIENT_ID", "META_CLIENT_SECRET"]},
            )

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_creds()
        params = {
            "client_id": self._cid,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(SCOPES),
            "response_type": "code",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        self._require_creds()
        r = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "client_id": self._cid,
                "client_secret": self._secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        data = r.json()
        return OAuthTokenBundle(
            access_token=data["access_token"],
            refresh_token=None,  # Meta usa long-lived tokens, não refresh tokens
            expires_at=_expires_in_to_dt(data.get("expires_in")),
        )

    def refresh(self, refresh_token: str) -> OAuthTokenBundle:
        # Meta: troca long-lived token por outro long-lived (fb_exchange_token).
        self._require_creds()
        r = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._cid,
                "client_secret": self._secret,
                "fb_exchange_token": refresh_token,
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        data = r.json()
        return OAuthTokenBundle(
            access_token=data["access_token"],
            expires_at=_expires_in_to_dt(data.get("expires_in")),
        )

    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics:
        r = requests.get(
            f"{GRAPH}/me",
            params={"fields": "id,username,followers_count", "access_token": access_token},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        d = r.json()
        return ProfileMetrics(
            follower_count=int(d.get("followers_count", 0)),
            handle=d.get("username"),
            platform_user_id=d.get("id"),
        )

    def fetch_recent_posts(self, access_token: str, limit: int = 10) -> list[NormalizedPost]:
        r = requests.get(
            f"{GRAPH}/me/media",
            params={
                "fields": "id,caption,media_type,timestamp,thumbnail_url,media_url,"
                "like_count,comments_count,insights.metric(reach,impressions,saved,shares)",
                "limit": limit,
                "access_token": access_token,
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        out = []
        for item in r.json().get("data", []):
            insights = _flatten_ig_insights(item.get("insights", {}))
            reach = insights.get("reach", 0)
            out.append(
                NormalizedPost(
                    platform_post_id=item["id"],
                    post_type=_map_ig_type(item.get("media_type")),
                    posted_at=_parse_iso(item.get("timestamp")),
                    caption=item.get("caption"),
                    video_url=item.get("media_url") if item.get("media_type") == "VIDEO" else None,
                    thumbnail_url=item.get("thumbnail_url") or item.get("media_url"),
                    reach_total=reach,
                    reach_organic=reach,  # Graph não separa pago aqui sem ads API
                    reach_paid=0,
                    impressions=insights.get("impressions", 0),
                    likes=int(item.get("like_count", 0)),
                    comments_count=int(item.get("comments_count", 0)),
                    shares=insights.get("shares", 0),
                    saves=insights.get("saved", 0),
                )
            )
        return out

    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict:
        r = requests.get(
            f"{GRAPH}/{platform_post_id}/insights",
            params={"metric": "reach,impressions,saved,shares", "access_token": access_token},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        return _flatten_ig_insights(r.json())

    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]:
        r = requests.get(
            f"{GRAPH}/{platform_post_id}/comments",
            params={"fields": "id,text,username,timestamp,like_count", "limit": limit,
                    "access_token": access_token},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        return [
            NormalizedComment(
                platform_comment_id=c["id"],
                content=c.get("text", ""),
                author_handle=c.get("username"),
                posted_at=_parse_iso(c.get("timestamp")),
                like_count=int(c.get("like_count", 0)),
            )
            for c in r.json().get("data", [])
        ]


def _map_ig_type(media_type: str | None) -> PostType:
    return {
        "IMAGE": PostType.IMAGE,
        "VIDEO": PostType.REEL,
        "CAROUSEL_ALBUM": PostType.CAROUSEL,
    }.get(media_type or "", PostType.IMAGE)


def _flatten_ig_insights(insights: dict) -> dict:
    out: dict = {}
    for metric in insights.get("data", []):
        name = metric.get("name")
        values = metric.get("values", [])
        if name and values:
            out[name] = values[0].get("value", 0)
    return out


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("+0000", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _expires_in_to_dt(expires_in) -> datetime | None:
    if not expires_in:
        return None
    from datetime import timedelta

    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
