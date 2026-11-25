"""Blueprint /api/v1/integrations — OAuth das redes sociais (connect/callback/disconnect)."""
from __future__ import annotations

import uuid
from urllib.parse import urlencode

from flask import Blueprint, current_app, redirect, request, url_for

from src.models import UserRole
from src.services import integration_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import LuminaError, ValidationError
from src.utils.responses import ok
from src.models import Influencer

bp = Blueprint("integrations", __name__, url_prefix="/api/v1/integrations")


def callback_uri(platform: str) -> str:
    """O `redirect_uri` que esta aplicacao registra e espera de volta.

    Publica porque o provedor de demonstracao precisa comparar o valor recebido
    com este antes de redirecionar: e a checagem que substitui, localmente, a
    lista de URIs registradas no painel do provedor real.
    """
    base = current_app.config.get("OAUTH_REDIRECT_BASE")
    path = url_for("integrations.callback", platform=platform)
    if base:
        return base.rstrip("/") + path
    return url_for("integrations.callback", platform=platform, _external=True)


@bp.get("/<platform>/connect")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def connect(platform):
    """Gera a URL de autorização OAuth pra conectar uma conta ao influencer.

    `modo=popup` marca o fluxo como aberto numa janela à parte: o callback
    devolve a janela a `/conexao/concluida`, que avisa a aba do painel e fecha.
    """
    plat = integration_service.parse_platform(platform)
    influencer_id = request.args.get("influencer_id")
    if not influencer_id:
        raise ValidationError("influencer_id é obrigatório")
    influencer = get_scoped_or_404(Influencer, influencer_id)

    auth_url = integration_service.build_connect_url(
        influencer=influencer,
        platform=plat,
        agency_id=current_agency_id(),
        redirect_uri=callback_uri(platform),
        popup=request.args.get("modo") == "popup",
    )
    return ok({"auth_url": auth_url, "platform": platform})


def _state_de_popup(plat, state: str | None) -> dict | None:
    """O payload do state, se ele for legível e vier de uma janela popup.

    Só lê: gastar o nonce é trabalho do `handle_callback`. Serve ao caminho de
    erro, que precisa saber para onde devolver a janela antes de qualquer outra
    coisa.
    """
    if not state:
        return None
    try:
        payload = integration_service.verify_state(state, expected_platform=plat)
    except LuminaError:
        return None
    return payload if payload.get("pop") else None


def _concluida(plat, influencer_id: str | None, erro: str | None = None):
    """Redirect para a página do front que avisa o painel e fecha a janela."""
    destino = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    query = {"plataforma": plat.value, "popup": "1"}
    if influencer_id:
        query["influenciador"] = influencer_id
    if erro:
        query["erro"] = erro
    return redirect(f"{destino}/conexao/concluida?{urlencode(query)}")


@bp.get("/<platform>/callback")
def callback(platform):
    """Recebe o code, troca por tokens, criptografa e persiste a SocialAccount.

    Sem `@require_auth` de propósito: quem chega aqui é o browser redirecionado
    pelo provedor, numa navegação limpa que não carrega header Authorization —
    exigir Bearer tornava o endpoint inalcançável fora dos testes. A identidade
    vem do `state`, um JWT assinado com o JWT_SECRET, com validade de 15 minutos
    e agora de uso único. É o mesmo desenho do callback de login.

    Fluxo aberto em popup (marca `pop` no state) termina sempre em
    `/conexao/concluida` — inclusive no erro, que de outro jeito deixaria a
    janela pequena mostrando um JSON. Fora da popup, o comportamento é o de
    antes: sucesso volta à tela do criador, erro responde JSON.
    """
    plat = integration_service.parse_platform(platform)
    state = request.args.get("state")
    popup = _state_de_popup(plat, state)

    error = request.args.get("error")
    if error:
        if popup:
            return _concluida(plat, popup.get("inf"), erro=error[:40])
        raise ValidationError(
            f"Provedor retornou erro: {error}",
            details={"description": request.args.get("error_description")},
        )
    code = request.args.get("code")
    if not code or not state:
        raise ValidationError("Parâmetros code/state ausentes")

    try:
        account = integration_service.handle_callback(
            platform=plat,
            code=code,
            state=state,
            redirect_uri=callback_uri(platform),
        )
    except LuminaError as exc:
        if popup:
            return _concluida(plat, popup.get("inf"), erro=exc.code)
        raise

    if popup:
        return _concluida(plat, str(account.influencer_id))
    # O browser está nesta aba: devolver JSON deixaria o usuário olhando para um
    # payload. Volta para a tela do criador, na origem do front — e não em
    # AUTH_SUCCESS_REDIRECT, que aponta para a página de callback do login.
    destino = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    return redirect(
        f"{destino}/app/influenciadores/{account.influencer_id}?conectado={plat.value}"
    )


@bp.post("/<platform>/disconnect/<social_account_id>")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def disconnect(platform, social_account_id):
    """Remove os tokens da conta (desconecta), mantendo o histórico de posts."""
    integration_service.parse_platform(platform)  # valida nome
    try:
        sid = uuid.UUID(social_account_id)
    except ValueError as exc:
        from src.utils.errors import NotFoundError

        raise NotFoundError("SocialAccount não encontrada") from exc
    # O flag vem no corpo, não na query: é o que distingue desligar a coleta de
    # apagar o histórico, e parâmetro destrutivo em URL vaza em log de acesso.
    corpo = request.get_json(silent=True) or {}
    resultado = integration_service.disconnect_account(
        social_account_id=sid,
        agency_id=current_agency_id(),
        purge_collected=bool(corpo.get("purge_collected", False)),
    )
    return ok({"disconnected": str(sid), **resultado})
