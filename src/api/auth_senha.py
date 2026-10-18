"""Blueprint /api/v1/auth — entrada por e-mail e senha.

Mesmo prefixo do blueprint de OAuth (`auth.py`), em arquivo próprio: aquele
cuida de provedores externos; este, da credencial local, do cadastro e da
recuperação. Spec: docs/superpowers/specs/2026-10-15-login-cadastro-senha-design.md.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from src.integrations.brasilapi import consultar_cnpj
from src.schemas.auth import CnpjConsultaIn, EmailIn, RegisterIn, TokenIn
from src.services import cadastro_service
from src.services.auth_service import concluir_login
from src.utils.rate_limit import ip_do_cliente, limitar
from src.utils.validation import parse_json, validar_dados

bp = Blueprint("auth_senha", __name__, url_prefix="/api/v1/auth")


@bp.get("/cnpj/<path:valor>")
def consultar_cnpj_publico(valor: str):
    """Pública: o cadastro consulta antes de a conta existir."""
    limitar("RATE_LIMIT_CNPJ", ip_do_cliente())
    dados = validar_dados(CnpjConsultaIn, {"cnpj": valor})
    consulta = consultar_cnpj(dados.cnpj)
    return jsonify({"data": {
        "cnpj": dados.cnpj,
        "encontrado": consulta.encontrado,
        "razao_social": consulta.razao_social,
        "situacao": consulta.situacao,
        "impeditiva": consulta.impeditiva,
    }})


def _limitar_fluxo_de_email(email: str) -> None:
    # Depois da validação: errar um campo várias vezes não pode bloquear quem
    # está só corrigindo o formulário.
    limitar("RATE_LIMIT_EMAIL_FLOW_IP", ip_do_cliente())
    limitar("RATE_LIMIT_EMAIL_FLOW_EMAIL", email)


@bp.post("/register")
def register():
    dados = parse_json(RegisterIn)
    _limitar_fluxo_de_email(dados.email)
    cadastro_service.cadastrar(dados)
    return jsonify({"data": {"message": cadastro_service.MENSAGEM_LINK_ENVIADO}}), 202


@bp.post("/verify-email")
def verify_email():
    dados = parse_json(TokenIn)
    user = cadastro_service.verificar_email(dados.token)
    return jsonify({"data": concluir_login(user)})


@bp.post("/resend-verification")
def resend_verification():
    dados = parse_json(EmailIn)
    _limitar_fluxo_de_email(dados.email)
    cadastro_service.reenviar_verificacao(dados.email)
    return jsonify({"data": {"message": cadastro_service.MENSAGEM_SE_HOUVER_CONTA}}), 202
