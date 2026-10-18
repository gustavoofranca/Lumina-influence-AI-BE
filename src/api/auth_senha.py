"""Blueprint /api/v1/auth — entrada por e-mail e senha.

Mesmo prefixo do blueprint de OAuth (`auth.py`), em arquivo próprio: aquele
cuida de provedores externos; este, da credencial local, do cadastro e da
recuperação. Spec: docs/superpowers/specs/2026-10-15-login-cadastro-senha-design.md.
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify

from src.integrations.brasilapi import consultar_cnpj
from src.schemas.auth import (
    ChangePasswordIn, CnpjConsultaIn, EmailIn, LoginIn, RegisterIn, ResetPasswordIn, TokenIn,
)
from src.services import cadastro_service, senha_service
from src.services.auth_service import concluir_login
from src.utils.auth_decorators import require_auth
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


@bp.get("/options")
def opcoes():
    """O que a tela de login deve oferecer neste ambiente."""
    cfg = current_app.config
    return jsonify({"data": {
        "dev_login": bool(cfg.get("DEV_LOGIN_ENABLED")),
        "google": bool(cfg.get("GOOGLE_CLIENT_ID")),
    }})


@bp.post("/login")
def login():
    dados = parse_json(LoginIn)
    user = senha_service.entrar(dados.email, dados.password)
    return jsonify({"data": concluir_login(user)})


@bp.post("/forgot-password")
def forgot_password():
    dados = parse_json(EmailIn)
    _limitar_fluxo_de_email(dados.email)
    senha_service.esqueci_senha(dados.email)
    return jsonify({"data": {"message": cadastro_service.MENSAGEM_SE_HOUVER_CONTA}}), 202


@bp.post("/reset-password")
def reset_password():
    dados = parse_json(ResetPasswordIn)
    senha_service.redefinir_senha(dados.token, dados.password)
    return "", 204


@bp.post("/change-password")
@require_auth
def change_password():
    dados = parse_json(ChangePasswordIn)
    user = senha_service.trocar_senha(g.current_user, dados.current_password, dados.new_password)
    return jsonify({"data": concluir_login(user)})


@bp.post("/accept-terms")
@require_auth
def accept_terms():
    senha_service.aceitar_termos(g.current_user)
    return "", 204
