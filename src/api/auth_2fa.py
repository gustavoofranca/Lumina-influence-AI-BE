"""Blueprint /api/v1/auth/2fa — verificação em duas etapas por app autenticador.

Spec: docs/superpowers/specs/2026-10-19-2fa-totp-design.md.

O login devolve um ticket no lugar da sessão quando falta o segundo fator
(`auth_service.concluir_login`). Estas rotas trocam o ticket pela sessão: o de
desafio, com um código; o de ativação, ativando o 2FA. A ativação também pode
ser feita de dentro de uma sessão, por quem não é obrigado a ter 2FA.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from src.extensions import db
from src.models import FinalidadeToken, User
from src.schemas.auth import MfaCodeIn, MfaConfirmIn, MfaDisableIn, MfaSetupIn, MfaVerifyIn
from src.services import dois_fatores_service, token_service
from src.services.auth_service import concluir_login
from src.utils.auth_decorators import autenticar_sessao, require_auth
from src.utils.validation import parse_json

bp = Blueprint("auth_2fa", __name__, url_prefix="/api/v1/auth/2fa")


def _quem_ativa(mfa_ticket: str | None) -> User:
    """Dono do ticket de ativação, ou o usuário da sessão quando não há ticket."""
    if mfa_ticket:
        return token_service.ler(mfa_ticket, FinalidadeToken.ATIVAR_2FA)
    return autenticar_sessao()


@bp.post("/verify")
def verify():
    dados = parse_json(MfaVerifyIn)
    # Lê sem gastar: errar o código não pode obrigar a digitar a senha de novo.
    user = token_service.ler(dados.mfa_ticket, FinalidadeToken.DESAFIO_2FA)
    dois_fatores_service.verificar_codigo(user, dados.code)
    token_service.consumir(dados.mfa_ticket, FinalidadeToken.DESAFIO_2FA)
    db.session.commit()
    return jsonify({"data": concluir_login(user, exigir_2fa=False)})


@bp.post("/setup")
def setup():
    dados = parse_json(MfaSetupIn)
    user = _quem_ativa(dados.mfa_ticket)
    return jsonify({"data": dois_fatores_service.iniciar_ativacao(user)})


@bp.post("/setup/confirm")
def confirm():
    dados = parse_json(MfaConfirmIn)
    user = _quem_ativa(dados.mfa_ticket)
    codigos = dois_fatores_service.confirmar_ativacao(user, dados.code)
    if dados.mfa_ticket:
        token_service.consumir(dados.mfa_ticket, FinalidadeToken.ATIVAR_2FA)
    db.session.commit()
    # Sessão nova nos dois casos: a ativação encerrou as anteriores.
    return jsonify({"data": {"recovery_codes": codigos, **concluir_login(user, exigir_2fa=False)}})


@bp.post("/recovery-codes")
@require_auth
def recovery_codes():
    dados = parse_json(MfaCodeIn)
    codigos = dois_fatores_service.novos_codigos(g.current_user, dados.code)
    return jsonify({"data": {"recovery_codes": codigos}})


@bp.post("/disable")
@require_auth
def disable():
    dados = parse_json(MfaDisableIn)
    dois_fatores_service.desativar(g.current_user, dados.code, dados.password)
    return "", 204
