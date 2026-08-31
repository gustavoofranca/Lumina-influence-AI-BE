"""Adaptador Instagram via Meta Graph API.

Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login
Configuração: *Instagram API with Facebook Login*. É a única que expõe insights
— a variante com login pelo próprio Instagram (`graph.instagram.com`) não tem
`instagram_manage_insights`, e sem insights não existe auditoria de alcance.

Duas consequências dessa escolha moldam o código abaixo:

1. O token que sai do login é de *usuário do Facebook*. `/me` nele é a pessoa,
   não o perfil do Instagram: `followers_count` e `media` não existem nesse nó.
   O caminho documentado é listar as Páginas, achar a que tem
   `instagram_business_account` e falar com o ID e o token *daquela Página*.
2. Só funciona com conta Business/Creator vinculada a uma Página. Conta pessoal
   autoriza e não devolve nada — daí `AccountNotLinkedError`, para o front dizer
   o que está errado em vez de mostrar um perfil vazio.

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
    AccountNotLinkedError,
    NormalizedComment,
    NormalizedPost,
    OAuthTokenBundle,
    PlatformNotConfiguredError,
    ProfileMetrics,
    SocialAdapter,
    raise_for_social_status,
)
from src.models import PostType

# v25.0 (fev/2026) em vez da mais nova: expira só em jul/2028 e já é a primeira
# posterior à remoção de `impressions`, então documentação e comportamento
# estão estáveis. A v21.0 que estava aqui expira em jan/2027.
API_VERSION = "v25.0"
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
AUTH_URL = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"

# `pages_show_list` lista as Páginas e traz o token de cada uma;
# `pages_read_engagement` é o que autoriza ler a Página encontrada. Sem o
# segundo, o passo 1 funciona e o passo 2 devolve 403 — falha que só aparece
# em produção, depois do App Review.
SCOPES = [
    "instagram_basic",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
]

# `impressions` foi removida na v22.0 (21/04/2025) e hoje devolve erro para
# mídia criada a partir de 02/07/2024. `views` é a substituta unificada — o
# mesmo número que YouTube e TikTok já gravam no campo interno `impressions`.
MEDIA_INSIGHTS = ("reach", "views", "saved", "shares")

TIMEOUT = 15


class InstagramAdapter(SocialAdapter):
    platform = "instagram"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self._cid = client_id or current_app.config.get("META_CLIENT_ID")
        self._secret = client_secret or current_app.config.get("META_CLIENT_SECRET")
        # Descoberta da conta custa uma chamada e não muda durante um sync, que
        # usa a mesma instância para perfil, mídia e comentários de cada post.
        self._conta: tuple[str, str] | None = None

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

    # ----------------------------------------------------------------------
    # Descoberta da conta profissional
    # ----------------------------------------------------------------------
    def _conta_instagram(self, access_token: str) -> tuple[str, str]:
        """Devolve `(ig_user_id, page_token)` da Página com Instagram vinculado.

        O token de Página é o que a Graph API aceita nas rotas de mídia,
        insights e comentários do Instagram; o token de usuário não serve.
        """
        if self._conta is not None:
            return self._conta

        r = requests.get(
            f"{GRAPH}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id}",
                "access_token": access_token,
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        paginas = r.json().get("data", [])

        for pagina in paginas:
            ig_id = (pagina.get("instagram_business_account") or {}).get("id")
            if not ig_id:
                continue
            token_pagina = pagina.get("access_token")
            if not token_pagina:
                # A Página existe e tem Instagram, mas veio sem token: é escopo
                # faltando, não conta desvinculada. Distinguir importa porque a
                # orientação ao usuário é oposta.
                raise PlatformNotConfiguredError(
                    "Página sem token na resposta — escopo pages_show_list ausente",
                    details={"page_id": pagina.get("id")},
                )
            self._conta = (ig_id, token_pagina)
            return self._conta

        raise AccountNotLinkedError(
            "Nenhuma Página do Facebook com conta profissional do Instagram vinculada",
            details={"pages_found": len(paginas)},
        )

    # ----------------------------------------------------------------------
    # Coleta
    # ----------------------------------------------------------------------
    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics:
        ig_id, token_pagina = self._conta_instagram(access_token)
        r = requests.get(
            f"{GRAPH}/{ig_id}",
            params={"fields": "id,username,followers_count", "access_token": token_pagina},
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
        ig_id, token_pagina = self._conta_instagram(access_token)
        r = requests.get(
            f"{GRAPH}/{ig_id}/media",
            params={
                "fields": "id,caption,media_type,media_product_type,timestamp,"
                "thumbnail_url,media_url,like_count,comments_count,"
                f"insights.metric({','.join(MEDIA_INSIGHTS)})",
                "limit": limit,
                "access_token": token_pagina,
            },
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        out = []
        for item in r.json().get("data", []):
            insights = _flatten_ig_insights(item.get("insights", {}))
            reach = insights.get("reach", 0)
            eh_video = item.get("media_type") == "VIDEO"
            out.append(
                NormalizedPost(
                    platform_post_id=item["id"],
                    post_type=_map_ig_type(item.get("media_type"), item.get("media_product_type")),
                    posted_at=_parse_iso(item.get("timestamp")),
                    caption=item.get("caption"),
                    video_url=item.get("media_url") if eh_video else None,
                    thumbnail_url=item.get("thumbnail_url") or item.get("media_url"),
                    reach_total=reach,
                    reach_organic=reach,  # Graph não separa pago aqui sem ads API (ADR-005)
                    reach_paid=0,
                    impressions=insights.get("views", 0),
                    likes=int(item.get("like_count", 0)),
                    comments_count=int(item.get("comments_count", 0)),
                    shares=insights.get("shares", 0),
                    saves=insights.get("saved", 0),
                )
            )
        return out

    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict:
        _, token_pagina = self._conta_instagram(access_token)
        r = requests.get(
            f"{GRAPH}/{platform_post_id}/insights",
            params={"metric": ",".join(MEDIA_INSIGHTS), "access_token": token_pagina},
            timeout=TIMEOUT,
        )
        raise_for_social_status(r, platform=self.platform)
        return _flatten_ig_insights(r.json())

    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]:
        _, token_pagina = self._conta_instagram(access_token)
        r = requests.get(
            f"{GRAPH}/{platform_post_id}/comments",
            params={"fields": "id,text,username,timestamp,like_count", "limit": limit,
                    "access_token": token_pagina},
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


def _map_ig_type(media_type: str | None, media_product_type: str | None = None) -> PostType:
    """`media_type` sozinho chama todo vídeo de Reel.

    A Graph devolve `VIDEO` tanto para Reel quanto para vídeo de feed; quem
    separa é `media_product_type`. A distinção não é cosmética: Reel e vídeo de
    feed têm curvas de alcance diferentes, e o benchmarking compara por tipo.
    """
    if media_type == "VIDEO":
        return PostType.REEL if media_product_type == "REELS" else PostType.VIDEO
    return {
        "IMAGE": PostType.IMAGE,
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
