"""Blueprint /api/v1/auth — entrada por e-mail e senha.

Mesmo prefixo do blueprint de OAuth (`auth.py`), em arquivo próprio: aquele
cuida de provedores externos; este, da credencial local, do cadastro e da
recuperação. Spec: docs/superpowers/specs/2026-10-15-login-cadastro-senha-design.md.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from src.integrations.brasilapi import consultar_cnpj
from src.schemas.auth import CnpjConsultaIn
from src.utils.rate_limit import ip_do_cliente, limitar
from src.utils.validation import validar_dados

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
