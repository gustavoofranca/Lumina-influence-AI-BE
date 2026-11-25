"""Refresh token em cookie httpOnly (ADR-001, revisão de 25/11/2026).

O refresh token deixa de passar pelo JavaScript: vai num cookie que o navegador
guarda e só devolve às rotas de `/api/v1/auth`. É o que deixa a sessão
sobreviver à aba sem pôr credencial de 30 dias onde um XSS leria
(OWASP Session Management Cheat Sheet, "Cookies"; JWT Cheat Sheet, "Token
Storage on Client Side").

- `HttpOnly`: `document.cookie` não enxerga.
- `SameSite=Strict`: o navegador não manda o cookie em pedido iniciado por
  outro site. Front (`lumina.<dominio>`) e API (`api.lumina.<dominio>`) são o
  mesmo *site*, e em dev `localhost:5173` e `localhost:5000` também.
- `Path=/api/v1/auth`: as outras rotas nem recebem o cookie.
- Cabeçalho `X-Lumina-Csrf` exigido quando a credencial vem do cookie: pedido
  com cabeçalho próprio dispara preflight de CORS, que só a `FRONTEND_ORIGIN`
  passa (OWASP CSRF Cheat Sheet, "Custom Request Headers"). É a segunda camada,
  para navegador que não aplique o `SameSite`.
"""
from __future__ import annotations

from flask import Response, current_app, jsonify, request

from src.utils.errors import ForbiddenError

NOME_DO_COOKIE = "lumina_refresh"
CABECALHO_CSRF = "X-Lumina-Csrf"
CAMINHO_DO_COOKIE = "/api/v1/auth"


def gravar_cookie_de_refresh(resp: Response, refresh_token: str) -> Response:
    resp.set_cookie(
        NOME_DO_COOKIE,
        refresh_token,
        max_age=int(current_app.config["JWT_REFRESH_TTL"].total_seconds()),
        path=CAMINHO_DO_COOKIE,
        secure=current_app.config.get("REFRESH_COOKIE_SECURE", True),
        httponly=True,
        samesite="Strict",
    )
    return resp


def apagar_cookie_de_refresh(resp: Response) -> Response:
    # Os mesmos atributos da gravação: o navegador só apaga o cookie que casa
    # nome, caminho e domínio.
    resp.delete_cookie(
        NOME_DO_COOKIE,
        path=CAMINHO_DO_COOKIE,
        secure=current_app.config.get("REFRESH_COOKIE_SECURE", True),
        httponly=True,
        samesite="Strict",
    )
    return resp


def refresh_do_cookie() -> str | None:
    """Refresh token do cookie, exigindo o cabeçalho anti-CSRF junto."""
    token = request.cookies.get(NOME_DO_COOKIE)
    if not token:
        return None
    if request.headers.get(CABECALHO_CSRF) != "1":
        raise ForbiddenError(
            "Cabeçalho de proteção ausente", code="csrf_header_missing"
        )
    return token


def resposta_de_sessao(dados: dict, status: int = 200) -> Response:
    """Resposta JSON de um login: o refresh vai para o cookie, não para o corpo.

    Resposta sem par de tokens (ticket de 2FA) passa como veio.
    """
    tokens = dados.get("tokens") or {}
    refresh = tokens.get("refresh_token")
    if not refresh:
        resp = jsonify({"data": dados})
        resp.status_code = status
        return resp
    corpo = {**dados, "tokens": {k: v for k, v in tokens.items() if k != "refresh_token"}}
    resp = jsonify({"data": corpo})
    resp.status_code = status
    return gravar_cookie_de_refresh(resp, refresh)
