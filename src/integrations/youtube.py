"""Adaptador YouTube via YouTube Data API v3 + Analytics API.

Docs: https://developers.google.com/youtube/v3
OAuth: Google OAuth (escopo youtube.readonly, yt-analytics.readonly). Usa as
credenciais do Google (mesmo projeto do login). Não exige App Review da Meta —
é a plataforma mais acessível de habilitar.
"""
from __future__ import annotations

import logging
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
# A Analytics API é um host próprio, e não um recurso da Data API v3. Só ela
# entrega tempo de exibição e retenção — a v3 não expõe nenhum dos dois.
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"

logger = logging.getLogger(__name__)
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # force-ssl é o único escopo que autoriza `commentThreads.list`: com apenas
    # readonly a chamada volta 403 insufficient authentication scopes, e sem
    # comentário a análise de sentimento de conta real fica sem base. Ele
    # concede escrita que o sistema não exerce — ver ADR-006.
    "https://www.googleapis.com/auth/youtube.force-ssl",
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

        # 3) Retenção, da YouTube Analytics API. Best-effort de propósito: ver
        #    `_retencao_por_video`.
        retencao = self._retencao_por_video(headers, ids)

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
                    # `None` quando a Analytics não respondeu ou não tem dado do
                    # vídeo — nunca 0. Retenção zero é uma afirmação forte
                    # ("ninguém assistiu"), e ausência de medição não é isso
                    # (ADR-003).
                    **retencao.get(item["id"], {}),
                )
            )
        return out

    def _retencao_por_video(self, headers: dict, ids: list[str]) -> dict[str, dict]:
        """Tempo médio de exibição e retenção, por vídeo, da Analytics API.

        Estes dois campos existiam no modelo, no schema e no tipo normalizado
        desde a B7, e o painel já os consumia — só ninguém os coletava. Para a
        conta real conectada na B8 chegavam sempre nulos, e nas de demonstração
        vinham inventados pelo seed. O escopo `yt-analytics.readonly` já estava
        concedido: faltava a chamada.

        **Best-effort, e por um motivo.** A Analytics API responde 403 para
        canal sem histórico de proprietário, e devolve linha vazia para vídeo
        recém-publicado. Nenhum dos dois é motivo para perder a coleta dos
        posts: a retenção é um enfeite do painel, o alcance é o produto. A
        falha vira aviso e os campos ficam nulos.

        `averageViewDuration` vem em **segundos** e `averageViewPercentage` em
        0–100 — o campo interno é fração, daí a divisão por 100.
        """
        hoje = datetime.now(timezone.utc).date()
        try:
            r = requests.get(
                ANALYTICS,
                params={
                    "ids": "channel==MINE",
                    # A janela precisa cobrir os vídeos pedidos; um ano cobre o
                    # que `search` devolve com folga, e a API exige as duas datas.
                    "startDate": (hoje - timedelta(days=365)).isoformat(),
                    "endDate": hoje.isoformat(),
                    "metrics": "averageViewDuration,averageViewPercentage",
                    "dimensions": "video",
                    # Até 500 ids por chamada; `limit` aqui é uma dezena.
                    "filters": "video==" + ",".join(ids),
                },
                headers=headers,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("youtube analytics indisponível: %s", exc.__class__.__name__)
            return {}

        if r.status_code != 200:
            # 403 é o caso comum: o token autoriza analytics, mas o canal não
            # tem relatório de proprietário. Não é defeito do sistema.
            logger.info(
                "youtube analytics recusou (%s): retenção fica ausente", r.status_code
            )
            return {}

        corpo = r.json()
        # A ordem das colunas vem em `columnHeaders`; assumir posição fixa
        # quebraria em silêncio se a API acrescentasse coluna.
        colunas = [c.get("name") for c in corpo.get("columnHeaders", [])]
        try:
            i_video = colunas.index("video")
            i_duracao = colunas.index("averageViewDuration")
            i_pct = colunas.index("averageViewPercentage")
        except ValueError:
            logger.warning("youtube analytics sem as colunas esperadas: %s", colunas)
            return {}

        saida: dict[str, dict] = {}
        for linha in corpo.get("rows", []) or []:
            if len(linha) <= max(i_video, i_duracao, i_pct):
                continue
            campos = {}
            duracao = linha[i_duracao]
            pct = linha[i_pct]
            if duracao is not None:
                campos["avg_watch_time"] = float(duracao)
            if pct is not None:
                campos["retention_rate"] = round(float(pct) / 100, 4)
            if campos:
                saida[str(linha[i_video])] = campos
        return saida

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
