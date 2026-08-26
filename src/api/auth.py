"""Blueprint /api/v1/auth — fluxo OAuth Google + Microsoft + JWT.

Endpoints:
- GET  /api/v1/auth/google/login
- GET  /api/v1/auth/google/callback
- GET  /api/v1/auth/microsoft/login
- GET  /api/v1/auth/microsoft/callback
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout
- GET  /api/v1/auth/me
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, redirect, request, url_for

from src.integrations.google_oauth import GoogleOAuthClient
from src.integrations.microsoft_oauth import MicrosoftOAuthClient
from src.models import OAuthProvider as OAuthProviderEnum
from src.schemas.auth import (
    AgencySummaryOut,
    LoginCallbackOut,
    MeOut,
    TokenPairOut,
    UserOut,
)
from src.services.auth_service import (
    consume_oauth_state,
    create_oauth_state,
    find_or_create_user_from_oauth,
    resolve_dev_login_user,
)
from src.utils.auth_decorators import require_auth, require_refresh
from src.utils.errors import ForbiddenError, UnauthorizedError, ValidationError
from src.utils.jwt_utils import issue_token_pair

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _build_redirect_uri(endpoint: str) -> str:
    """Constrói o redirect URI usando o host atual da request.

    Sobrescrevível via config OAUTH_REDIRECT_BASE (útil em prod atrás de proxy).
    """
    override = current_app.config.get("OAUTH_REDIRECT_BASE")
    if override:
        return override.rstrip("/") + url_for(endpoint)
    return url_for(endpoint, _external=True)


def _build_login_response(user) -> dict:
    tokens = issue_token_pair(user)
    ttl_seconds = int(current_app.config["JWT_ACCESS_TTL"].total_seconds())
    payload = LoginCallbackOut(
        user=UserOut.model_validate(user),
        agency=AgencySummaryOut.model_validate(user.agency) if user.agency else None,
        tokens=TokenPairOut(**tokens, expires_in_seconds=ttl_seconds),
    )
    return payload.model_dump(mode="json")


def _login_result(user, *, agencia_criada: bool = False):
    """Resposta de sucesso do login: redireciona pro front (SPA) ou retorna JSON (API).

    `agencia_criada` viaja junto porque só este momento sabe que a agência
    nasceu agora: o front usa a marca para pedir o nome dela antes de seguir.
    """
    from urllib.parse import urlencode

    redirect_base = current_app.config.get("AUTH_SUCCESS_REDIRECT")
    tokens = issue_token_pair(user)
    if redirect_base:
        # Tokens no fragmento (#) — não vão pro servidor nem ficam em logs/histórico.
        campos = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }
        if agencia_criada:
            campos["new_agency"] = "1"
        return redirect(f"{redirect_base}#{urlencode(campos)}")
    payload = _build_login_response(user)
    payload["new_agency"] = agencia_criada
    return jsonify({"data": payload})


# --------------------------------------------------------------------------
# Google
# --------------------------------------------------------------------------
@bp.get("/google/login")
def google_login():
    client = GoogleOAuthClient()
    state = create_oauth_state(OAuthProviderEnum.GOOGLE)
    redirect_uri = _build_redirect_uri("auth.google_callback")
    return redirect(client.build_auth_url(state=state, redirect_uri=redirect_uri))


@bp.get("/google/callback")
def google_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error:
        raise ValidationError(
            f"Google retornou erro: {error}",
            details={"error_description": request.args.get("error_description")},
        )
    if not code or not state:
        raise ValidationError("Parâmetros code/state ausentes")

    consume_oauth_state(OAuthProviderEnum.GOOGLE, state)

    client = GoogleOAuthClient()
    redirect_uri = _build_redirect_uri("auth.google_callback")
    token_resp = client.exchange_code(code=code, redirect_uri=redirect_uri)
    access_token = token_resp["access_token"]
    user_info = client.fetch_user_info(access_token)

    user, agencia_criada = find_or_create_user_from_oauth(
        provider=OAuthProviderEnum.GOOGLE,
        oauth_id=user_info.oauth_id,
        email=user_info.email,
        name=user_info.name,
        avatar_url=user_info.avatar_url,
    )
    return _login_result(user, agencia_criada=agencia_criada)


# --------------------------------------------------------------------------
# Microsoft
# --------------------------------------------------------------------------
@bp.get("/microsoft/login")
def microsoft_login():
    client = MicrosoftOAuthClient()
    state = create_oauth_state(OAuthProviderEnum.MICROSOFT)
    redirect_uri = _build_redirect_uri("auth.microsoft_callback")
    return redirect(client.build_auth_url(state=state, redirect_uri=redirect_uri))


@bp.get("/microsoft/callback")
def microsoft_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error:
        raise ValidationError(
            f"Microsoft retornou erro: {error}",
            details={"error_description": request.args.get("error_description")},
        )
    if not code or not state:
        raise ValidationError("Parâmetros code/state ausentes")

    consume_oauth_state(OAuthProviderEnum.MICROSOFT, state)

    client = MicrosoftOAuthClient()
    redirect_uri = _build_redirect_uri("auth.microsoft_callback")
    token_resp = client.exchange_code(code=code, redirect_uri=redirect_uri)
    access_token = token_resp["access_token"]
    user_info = client.fetch_user_info(access_token)

    user, agencia_criada = find_or_create_user_from_oauth(
        provider=OAuthProviderEnum.MICROSOFT,
        oauth_id=user_info.oauth_id,
        email=user_info.email,
        name=user_info.name,
        avatar_url=user_info.avatar_url,
    )
    return _login_result(user, agencia_criada=agencia_criada)


# --------------------------------------------------------------------------
# Refresh / Logout / Me
# --------------------------------------------------------------------------
@bp.post("/dev-login")
def dev_login():
    """Atalho de login local (sem OAuth): emite JWT para um usuário seedado.

    Habilitado só fora de produção (DEV_LOGIN_ENABLED). Body opcional: {"email": "..."}.
    Sem email, usa o primeiro admin com email da agência seedada.
    """
    if not current_app.config.get("DEV_LOGIN_ENABLED", False):
        raise ForbiddenError("dev-login desabilitado", code="dev_login_disabled")

    body = request.get_json(silent=True) or {}
    user = resolve_dev_login_user(body.get("email"))

    if user is None:
        raise UnauthorizedError(
            "Nenhum usuário disponível para dev-login (rode `flask seed run`)",
            code="dev_login_no_user",
        )
    return jsonify({"data": _build_login_response(user)})


@bp.post("/refresh")
@require_refresh
def refresh_token():
    user = g.current_user
    tokens = issue_token_pair(user)
    ttl_seconds = int(current_app.config["JWT_ACCESS_TTL"].total_seconds())
    return jsonify(
        {"data": TokenPairOut(**tokens, expires_in_seconds=ttl_seconds).model_dump(mode="json")}
    )


@bp.post("/logout")
@require_auth
def logout():
    # Stateless JWT — client descarta tokens. Documentado em ADR-001.
    return "", 204


@bp.get("/me")
@require_auth
def me():
    user = g.current_user
    payload = MeOut(
        user=UserOut.model_validate(user),
        agency=AgencySummaryOut.model_validate(user.agency) if user.agency else None,
    )
    return jsonify({"data": payload.model_dump(mode="json")})
