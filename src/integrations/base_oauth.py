"""Contrato comum dos providers OAuth (Google, Microsoft, ...).

Mantemos a interface mínima: construir auth URL, trocar code por tokens, obter userinfo.
Cada provider concreto encapsula seus endpoints e payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OAuthUserInfo:
    """Resultado normalizado do userinfo do provider."""

    provider: str
    oauth_id: str
    email: str
    name: str
    avatar_url: str | None = None


class OAuthProviderClient(Protocol):
    provider: str

    def build_auth_url(self, *, state: str, redirect_uri: str) -> str: ...
    def exchange_code(self, *, code: str, redirect_uri: str) -> dict: ...
    def fetch_user_info(self, access_token: str) -> OAuthUserInfo: ...
