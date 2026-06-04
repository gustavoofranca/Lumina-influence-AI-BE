"""Cliente OAuth 2.0 + Microsoft Graph (tenant `common` = multi-tenant + pessoal).

Endpoints (Microsoft Entra ID v2.0):
- Authorize: https://login.microsoftonline.com/common/oauth2/v2.0/authorize
- Token:     https://login.microsoftonline.com/common/oauth2/v2.0/token
- UserInfo:  https://graph.microsoft.com/v1.0/me
"""
from __future__ import annotations

from urllib.parse import urlencode

import requests
from flask import current_app

from src.integrations.base_oauth import OAuthUserInfo
from src.utils.errors import LuminaError

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
DEFAULT_SCOPES = ["openid", "email", "profile", "User.Read"]
PROVIDER = "microsoft"


class MicrosoftOAuthError(LuminaError):
    status_code = 502
    code = "microsoft_oauth_error"


class MicrosoftOAuthClient:
    provider = PROVIDER

    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self._client_id = client_id or current_app.config.get("MICROSOFT_CLIENT_ID")
        self._client_secret = client_secret or current_app.config.get("MICROSOFT_CLIENT_SECRET")
        if not self._client_id or not self._client_secret:
            raise MicrosoftOAuthError(
                "Credenciais Microsoft não configuradas",
                details={"missing": ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"]},
            )

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "response_mode": "query",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        data = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(DEFAULT_SCOPES),
        }
        try:
            r = requests.post(TOKEN_URL, data=data, timeout=10)
        except requests.RequestException as exc:
            raise MicrosoftOAuthError(
                "Falha ao contactar Microsoft", details={"err": str(exc)}
            ) from exc

        if r.status_code != 200:
            raise MicrosoftOAuthError(
                "Microsoft rejeitou o code",
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
            raise MicrosoftOAuthError(
                "Falha ao buscar userinfo", details={"err": str(exc)}
            ) from exc

        if r.status_code != 200:
            raise MicrosoftOAuthError(
                "Graph /me retornou erro",
                details={"status": r.status_code, "body": r.text[:500]},
            )
        data = r.json()
        # Graph retorna id, userPrincipalName, mail, displayName
        email = data.get("mail") or data.get("userPrincipalName")
        if not email:
            raise MicrosoftOAuthError(
                "Conta Microsoft sem email", details={"data_keys": list(data.keys())}
            )
        return OAuthUserInfo(
            provider=PROVIDER,
            oauth_id=data["id"],
            email=email,
            name=data.get("displayName") or email.split("@")[0],
            avatar_url=None,
        )
