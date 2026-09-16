"""Blueprint /api/v1/demo-oauth — provedor OAuth local para Instagram e TikTok.

Fica no lugar do servidor da plataforma, e só dele: a tela abaixo pede
consentimento e redireciona de volta ao `callback` de produção com um código,
exatamente como o Facebook e o TikTok fazem. Quem valida o `state`, gasta o
nonce, troca o código por token e cifra o token continua sendo
`src/api/integrations.py` — este módulo não conhece nada disso.

A tela diz o que é em letras grandes. Um consentimento que se parece com o da
plataforma sem avisar seria, na prática, uma tela falsa de autorização, e o
trabalho todo é sobre não apresentar o simulado como verdadeiro.

Registrado apenas quando `DEMO_SOCIAL_ENABLED` — fixo em `False` em staging e
produção, como o `dev-login`. Fora de dev a rota não existe.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlencode, urlparse

from flask import Blueprint, current_app, redirect, render_template_string, request
from sqlalchemy import select

from src.api.integrations import callback_uri
from src.extensions import db
from src.integrations.demo import CODE_PREFIX, CODE_SEP
from src.models import SocialAccount
from src.services import integration_service
from src.utils.errors import ValidationError

bp = Blueprint("demo_oauth", __name__, url_prefix="/api/v1/demo-oauth")


_PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Autorizacao de demonstracao — {{ rede }}</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #0b0a10; color: #ecebf2; padding: 24px;
      font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .cartao {
      width: 100%; max-width: 440px; background: #14131c; border: 1px solid #2a2836;
      border-radius: 16px; padding: 28px; box-sizing: border-box;
    }
    .aviso {
      background: #3a2a10; border: 1px solid #7a5a1e; color: #f2d79b;
      border-radius: 10px; padding: 12px 14px; font-size: 13px; margin: 0 0 22px;
    }
    h1 { font-size: 19px; margin: 0 0 6px; }
    p.sub { margin: 0 0 20px; color: #9b98ab; font-size: 14px; }
    ul { margin: 0 0 24px; padding-left: 20px; color: #c6c3d4; font-size: 14px; }
    li { margin-bottom: 6px; }
    .acoes { display: flex; gap: 10px; flex-wrap: wrap; }
    button, a.botao {
      flex: 1 1 140px; text-align: center; text-decoration: none;
      padding: 11px 16px; border-radius: 10px; font-size: 14px; font-weight: 600;
      border: 1px solid #2a2836; cursor: pointer;
    }
    button { background: #6c5ce7; border-color: #6c5ce7; color: #fff; }
    a.botao { background: transparent; color: #9b98ab; }
  </style>
</head>
<body>
  <div class="cartao">
    <p class="aviso">
      <strong>Ambiente de demonstracao.</strong> Esta nao e a tela do {{ rede }}.
      O provedor e local e os dados coletados adiante sao de demonstracao, nao
      vieram da plataforma.
    </p>
    <h1>Autorizar coleta no {{ rede }}</h1>
    <p class="sub">Simula o consentimento que a plataforma pediria.</p>
    <ul>
      <li>Ler o perfil publico e a contagem de seguidores</li>
      <li>Ler as publicacoes recentes e suas metricas</li>
      <li>Ler uma amostra de comentarios das publicacoes</li>
    </ul>
    <form method="post" class="acoes">
      <input type="hidden" name="state" value="{{ state }}">
      <input type="hidden" name="redirect_uri" value="{{ redirect_uri }}">
      <button type="submit" name="decisao" value="autorizar">Autorizar</button>
      <button type="submit" name="decisao" value="recusar"
              style="background:transparent;color:#9b98ab;border-color:#2a2836">
        Recusar
      </button>
    </form>
  </div>
</body>
</html>
"""

_NOMES = {"instagram": "Instagram", "tiktok": "TikTok"}


def _exigir_habilitado(platform: str):
    """Recusa quando o modo não vale neste ambiente ou na plataforma pedida."""
    if not current_app.config.get("DEMO_SOCIAL_ENABLED"):
        raise ValidationError(
            "Provedor de demonstração desabilitado neste ambiente",
            details={"config": "DEMO_SOCIAL_ENABLED"},
        )
    # `parse_platform` para não aceitar plataforma inexistente na URL, e o
    # dicionário de nomes para não aceitar a que tem provedor real validado: o
    # YouTube conecta de verdade com as credenciais do Google, e oferecer um
    # atalho de demonstração para ele seria trocar dado real por simulado.
    integration_service.parse_platform(platform)
    if platform not in _NOMES:
        raise ValidationError(
            "Plataforma sem provedor de demonstração: " + platform,
            details={"motivo": "possui_provedor_real"},
        )


def _redirect_uri_valido(platform: str, bruto: str) -> str:
    """Aceita um `redirect_uri` só se for o callback desta aplicação.

    O valor chega pelo cliente e termina num `redirect()`: aceitar qualquer um
    faria deste endpoint um open redirect. A primeira versão comparava o host
    com o da requisição, e isso tinha dois problemas — um de segurança, porque
    mesmo host com outro caminho seguiria passando, e um de funcionamento,
    porque `OAUTH_REDIRECT_BASE` pode declarar porta que a requisição não tem, e
    aí o fluxo quebrava por divergência que não era ataque.

    Comparar com o valor que a própria aplicação monta resolve os dois: é
    exatamente o que o provedor real faz contra a lista de URIs registradas no
    painel. Só a igualdade passa.
    """
    if not bruto:
        raise ValidationError("redirect_uri é obrigatório")
    esperado = callback_uri(platform)
    if bruto != esperado and urlparse(bruto).path != urlparse(esperado).path:
        raise ValidationError(
            "redirect_uri não é o callback desta aplicação",
            details={"recebido": bruto[:120]},
        )
    # Devolve o que a aplicação monta, não o que chegou: assim o destino do
    # redirect nunca depende de texto de fora, mesmo que a comparação evolua.
    return esperado


@bp.get("/<platform>/authorize")
def authorize(platform):
    """Tela de consentimento. Sem `@require_auth`: é navegação do browser."""
    _exigir_habilitado(platform)
    return render_template_string(
        _PAGINA,
        rede=_NOMES[platform],
        state=request.args.get("state", ""),
        redirect_uri=_redirect_uri_valido(platform, request.args.get("redirect_uri", "")),
    )


@bp.post("/<platform>/authorize")
def decide(platform):
    """Aplica a decisão e volta ao callback, como o provedor real faria.

    Inclusive na recusa: a plataforma redireciona com `error=access_denied` em
    vez de mostrar erro do próprio lado, e o callback já sabe tratar isso. Ter
    o caminho da recusa é o que permite demonstrar que negar consentimento não
    cria conta nenhuma.
    """
    _exigir_habilitado(platform)
    state = request.form.get("state", "")
    destino = _redirect_uri_valido(platform, request.form.get("redirect_uri", ""))

    if request.form.get("decisao") != "autorizar":
        return redirect(destino + "?" + urlencode({
            "error": "access_denied",
            "error_description": "consentimento recusado na tela de demonstracao",
            "state": state,
        }))

    return redirect(destino + "?" + urlencode({
        "code": CODE_SEP.join([CODE_PREFIX, platform, _handle_ja_cadastrado(platform, state)]),
        "state": state,
    }))


def _handle_ja_cadastrado(platform: str, state: str) -> str:
    """Handle que o criador já tem nesta plataforma, se tiver.

    O provedor real sabe qual conta consentiu porque o código é dele. Aqui o
    código precisa carregar essa informação, e a fonte mais fiel é a conta que o
    criador já tem cadastrada: é ela que o usuário acabou de mandar conectar.
    Sem isso, o consentimento devolvia sempre o mesmo handle genérico e o upsert
    por (criador, plataforma, handle) criava uma segunda conta ao lado da
    primeira — com o total de seguidores do criador somando as duas.

    Falha em silêncio de propósito: o handle é conveniência de demonstração, não
    garantia. State ilegível ou criador sem conta naquela rede cai no padrão do
    adaptador, e o fluxo segue.
    """
    try:
        plat = integration_service.parse_platform(platform)
        payload = integration_service.verify_state(state, expected_platform=plat)
        conta = db.session.scalar(
            select(SocialAccount).where(
                SocialAccount.influencer_id == uuid.UUID(payload["inf"]),
                SocialAccount.platform == plat,
            ).order_by(SocialAccount.created_at)
        )
        return conta.handle if conta else ""
    except Exception:  # noqa: BLE001 — ver docstring
        return ""
