"""TOTP (RFC 6238) com a biblioteca padrão.

Escrito à mão, e não com `pyotp`, por decisão do usuário: o cálculo são poucas
linhas de HMAC, provadas em `tests/test_totp.py` contra os vetores do Apêndice
B da RFC 6238. O que exige cuidado de verdade — aceitar cada código uma vez só
e limitar as tentativas — fica em `dois_fatores_service`, e teria de ser
escrito de qualquer forma.

Parâmetros: SHA-1, 6 dígitos, passo de 30 s. São os padrões da RFC e os únicos
que todos os apps autenticadores aceitam; trocar qualquer um deles faz parte
dos apps gerar códigos que o servidor não reconhece.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

PASSO_EM_SEGUNDOS = 30
DIGITOS = 6
EMISSOR = "Lumina"
# 160 bits, o tamanho que a RFC 4226 (§4) recomenda; o NIST SP 800-63B-4
# (§3.1.5.1) pede no mínimo 112.
BYTES_DO_SEGREDO = 20
# Um passo para cada lado: tolera relógio de celular adiantado ou atrasado em
# até 30 s sem alargar a janela além do que o desvio pede (NIST §3.1.5.2).
JANELA = 1


def gerar_segredo() -> str:
    """Segredo novo em base32, sem o `=` de preenchimento (32 caracteres)."""
    return base64.b32encode(secrets.token_bytes(BYTES_DO_SEGREDO)).decode("ascii").rstrip("=")


def _chave(segredo: str) -> bytes:
    preenchido = segredo + "=" * (-len(segredo) % 8)
    return base64.b32decode(preenchido, casefold=True)


def passo_atual(agora: float | None = None) -> int:
    return int((time.time() if agora is None else agora) // PASSO_EM_SEGUNDOS)


def codigo(segredo: str, passo: int, digitos: int = DIGITOS) -> str:
    """O código de `passo` (RFC 4226 §5.3, com o contador sendo o passo de tempo)."""
    mac = hmac.new(_chave(segredo), struct.pack(">Q", passo), hashlib.sha1).digest()
    deslocamento = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** digitos).zfill(digitos)


def passo_do_codigo(segredo: str, digitado, agora: float | None = None) -> int | None:
    """Passo da janela que gerou `digitado`, ou None.

    Percorre a janela inteira mesmo depois de achar, e compara em tempo
    constante: quanto a verificação demora não diz em qual passo o código caiu.
    """
    if not isinstance(digitado, str) or len(digitado) != DIGITOS or not digitado.isdigit():
        return None
    atual = passo_atual(agora)
    achado = None
    for passo in range(atual - JANELA, atual + JANELA + 1):
        if hmac.compare_digest(codigo(segredo, passo), digitado):
            achado = passo
    return achado


def uri_de_provisionamento(segredo: str, email: str) -> str:
    """O `otpauth://` que o QR code carrega (formato do Google Authenticator)."""
    rotulo = quote(f"{EMISSOR}:", safe=":") + quote(email, safe="")
    parametros = urlencode({
        "secret": segredo, "issuer": EMISSOR, "algorithm": "SHA1",
        "digits": DIGITOS, "period": PASSO_EM_SEGUNDOS,
    })
    return f"otpauth://totp/{rotulo}?{parametros}"
