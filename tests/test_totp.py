"""TOTP (RFC 6238) escrito com a biblioteca padrão.

A prova de que o cálculo está certo são os vetores oficiais do Apêndice B da
RFC 6238 — os mesmos que os apps autenticadores usam para se validar.
"""
from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlparse

import pytest

from src.utils import totp

# Apêndice B da RFC 6238: semente ASCII "12345678901234567890" (SHA-1), 8 dígitos.
SEMENTE_DA_RFC = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize("instante,esperado", [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
])
def test_vetores_do_apendice_b_da_rfc_6238(instante, esperado):
    assert totp.codigo(SEMENTE_DA_RFC, totp.passo_atual(instante), digitos=8) == esperado


def test_seis_digitos_sao_o_final_do_mesmo_numero():
    # A truncagem é módulo 10^d: o código de 6 dígitos é o fim do de 8.
    assert totp.codigo(SEMENTE_DA_RFC, totp.passo_atual(59)) == "287082"


def test_segredo_tem_160_bits_em_base32():
    segredo = totp.gerar_segredo()
    assert len(base64.b32decode(segredo)) == 20
    assert segredo != totp.gerar_segredo()


def test_aceita_o_passo_atual_e_um_de_cada_lado():
    segredo = totp.gerar_segredo()
    agora = 1_700_000_000
    passo = totp.passo_atual(agora)
    for deslocamento in (-1, 0, 1):
        digitado = totp.codigo(segredo, passo + deslocamento)
        assert totp.passo_do_codigo(segredo, digitado, agora=agora) == passo + deslocamento


def test_recusa_codigo_fora_da_janela():
    segredo = totp.gerar_segredo()
    agora = 1_700_000_000
    atrasado = totp.codigo(segredo, totp.passo_atual(agora) - 2)
    # Um código de 6 dígitos de outro passo pode coincidir por acaso (1 em 10^6);
    # o teste só vale quando não coincide com nenhum passo da janela.
    janela = {totp.codigo(segredo, totp.passo_atual(agora) + d) for d in (-1, 0, 1)}
    if atrasado not in janela:
        assert totp.passo_do_codigo(segredo, atrasado, agora=agora) is None


@pytest.mark.parametrize("digitado", ["", "12345", "1234567", "abcdef", "12 345", None, 123456])
def test_formato_invalido_e_recusado_sem_erro(digitado):
    assert totp.passo_do_codigo(totp.gerar_segredo(), digitado) is None


def test_uri_que_o_app_autenticador_le():
    uri = totp.uri_de_provisionamento("ABCDEFGHIJKLMNOP", "ana+teste@agencia.com.br")
    partes = urlparse(uri)
    assert partes.scheme == "otpauth" and partes.netloc == "totp"
    # O rótulo leva o emissor antes do e-mail, com o e-mail codificado.
    assert partes.path == "/Lumina:ana%2Bteste%40agencia.com.br"
    q = parse_qs(partes.query)
    assert q == {"secret": ["ABCDEFGHIJKLMNOP"], "issuer": ["Lumina"], "algorithm": ["SHA1"],
                 "digits": ["6"], "period": ["30"]}
