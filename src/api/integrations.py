"""Blueprint /api/v1/integrations — OAuth das redes sociais (connect/callback/disconnect)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import Blueprint, current_app, redirect, request, url_for

from src.models import UserRole
from src.services import integration_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import LuminaError, ValidationError
from src.utils.rate_limit import ip_do_cliente, limitar
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
    """O payload do state, se ele for legível e vier de popup ou de link.

    Só lê: gastar o nonce é trabalho do `handle_callback`. Serve ao caminho de
    erro, que precisa saber para onde devolver o navegador antes de qualquer
    outra coisa.
    """
    if not state:
        return None
    try:
        payload = integration_service.verify_state(state, expected_platform=plat)
    except LuminaError:
        return None
    return payload if (payload.get("pop") or payload.get("cv")) else None


def _concluida(plat, influencer_id: str | None, erro: str | None = None, *, convite: bool = False):
    """Redirect para a página do front que fecha o fluxo.

    Popup: `/conexao/concluida`, que avisa o painel e fecha a janela. Link do
    criador: `/conectar/concluido`, pública, porque quem autorizou não tem
    sessão no Lumina — e por isso sem o id do criador na URL.
    """
    destino = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    if convite:
        query = {"plataforma": plat.value}
        if erro:
            query["erro"] = erro
        return redirect(f"{destino}/conectar/concluido?{urlencode(query)}")
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

    convite = bool(popup and popup.get("cv"))
    error = request.args.get("error")
    if error:
        if popup:
            return _concluida(plat, popup.get("inf"), erro=error[:40], convite=convite)
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
            return _concluida(plat, popup.get("inf"), erro=exc.code, convite=convite)
        raise

    if popup:
        return _concluida(plat, str(account.influencer_id), convite=convite)
    # O browser está nesta aba: devolver JSON deixaria o usuário olhando para um
    # payload. Volta para a tela do criador, na origem do front — e não em
    # AUTH_SUCCESS_REDIRECT, que aponta para a página de callback do login.
    destino = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    return redirect(
        f"{destino}/app/influenciadores/{account.influencer_id}?conectado={plat.value}"
    )


# --------------------------------------------------------------------------
# Link de conexão para o criador
# --------------------------------------------------------------------------
@bp.post("/<platform>/connect-link")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def connect_link(platform):
    """Gera o link que a agência manda ao criador para ele autorizar a conta."""
    plat = integration_service.parse_platform(platform)
    corpo = request.get_json(silent=True) or {}
    influencer_id = corpo.get("influencer_id")
    if not influencer_id:
        raise ValidationError("influencer_id é obrigatório")
    influencer = get_scoped_or_404(Influencer, influencer_id)
    convite = integration_service.emitir_convite(
        influencer=influencer, platform=plat, agency_id=current_agency_id()
    )
    destino = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    return ok({
        "url": f"{destino}/conectar/{convite['token']}",
        "expires_at": convite["expires_at"].isoformat(),
        "platform": plat.value,
    })


@bp.get("/convite/<token>")
def convite_info(token):
    """O que a página pública mostra antes de a pessoa autorizar.

    Pública: quem abre é o criador, sem conta no Lumina. Devolve o mínimo para
    ele saber quem está pedindo e para qual perfil — nada de métrica ou de
    outros criadores da agência.
    """
    limitar("RATE_LIMIT_CONVITE", ip_do_cliente())
    influencer, plat, payload = integration_service.ler_convite(token)
    return ok({
        "influencer": influencer.display_name,
        "agency": influencer.agency.name if influencer.agency else None,
        "platform": plat.value,
        "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat(),
        "connected": integration_service.conta_conectada(influencer, plat),
    })


@bp.get("/convite/<token>/autorizar")
def convite_autorizar(token):
    """Leva o navegador do criador à tela de consentimento da rede."""
    limitar("RATE_LIMIT_CONVITE", ip_do_cliente())
    influencer, plat, _ = integration_service.ler_convite(token)
    if integration_service.conta_conectada(influencer, plat):
        return _concluida(plat, None, erro="ja_conectada", convite=True)
    auth_url = integration_service.build_connect_url(
        influencer=influencer,
        platform=plat,
        agency_id=influencer.agency_id,
        redirect_uri=callback_uri(plat.value),
        convite=True,
    )
    return redirect(auth_url)


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
