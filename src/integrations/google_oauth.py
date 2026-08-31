"""Cliente OAuth 2.0 + OIDC do Google.

Endpoints oficiais:
- Authorize: https://accounts.google.com/o/oauth2/v2/auth
- Token:     https://oauth2.googleapis.com/token
- UserInfo:  https://openidconnect.googleapis.com/v1/userinfo
"""
from __future__ import annotations

from urllib.parse import urlencode

import requests
from flask import current_app

from src.integrations.base_oauth import OAuthUserInfo
from src.utils.errors import LuminaError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DEFAULT_SCOPES = ["openid", "email", "profile"]
PROVIDER = "google"


class GoogleOAuthError(LuminaError):
    status_code = 502
    code = "google_oauth_error"


class GoogleOAuthClient:
    provider = PROVIDER

    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self._client_id = client_id or current_app.config.get("GOOGLE_CLIENT_ID")
        self._client_secret = client_secret or current_app.config.get("GOOGLE_CLIENT_SECRET")
        if not self._client_id or not self._client_secret:
            raise GoogleOAuthError(
                "Credenciais Google não configuradas",
                details={"missing": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]},
            )

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        data = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            r = requests.post(TOKEN_URL, data=data, timeout=10)
        except requests.RequestException as exc:
            raise GoogleOAuthError("Falha ao contactar Google", details={"err": str(exc)}) from exc

        if r.status_code != 200:
            raise GoogleOAuthError(
                "Google rejeitou o code",
                details={"status": r.status_code, "body": r.text[:500]},
            )
        return r.json()

    def fetch_user_info(self, access_token: str) -> OAuthUserInfo:
        try:
            r = requests.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise GoogleOAuthError("Falha ao buscar userinfo", details={"err": str(exc)}) from exc

        if r.status_code != 200:
            raise GoogleOAuthError(
                "UserInfo retornou erro",
                details={"status": r.status_code, "body": r.text[:500]},
            )
        data = r.json()
        # Campos OIDC padrão: sub, email, name, picture. Os dois primeiros são
        # a identidade em si — sem eles não há login, e o usuário pode não ter
        # concedido o escopo. Ler direto da chave transformaria isso em
        # KeyError e 500, escondendo a causa.
        faltando = [campo for campo in ("sub", "email") if not data.get(campo)]
        if faltando:
            raise GoogleOAuthError(
                "UserInfo do Google sem identidade",
                details={"missing": faltando, "data_keys": list(data.keys())},
            )
        return OAuthUserInfo(
            provider=PROVIDER,
            oauth_id=data["sub"],
            email=data["email"],
            name=data.get("name") or data["email"].split("@")[0],
            avatar_url=data.get("picture"),
        )
