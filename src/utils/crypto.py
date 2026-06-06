"""Criptografia simétrica (Fernet) dos tokens das APIs sociais em repouso.

Os tokens NUNCA são persistidos em texto claro. Esta camada cifra/decifra com a
FERNET_KEY do ambiente. Se a chave não estiver configurada, falha cedo e claro.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from src.utils.errors import LuminaError


class CryptoNotConfiguredError(LuminaError):
    status_code = 503
    code = "crypto_not_configured"


class TokenDecryptError(LuminaError):
    status_code = 500
    code = "token_decrypt_error"


@lru_cache(maxsize=4)
def _fernet_for(key: str) -> Fernet:
    return Fernet(key.encode() if isinstance(key, str) else key)


def _get_fernet() -> Fernet:
    key = current_app.config.get("FERNET_KEY")
    if not key:
        raise CryptoNotConfiguredError(
            "FERNET_KEY não configurada", details={"missing": ["FERNET_KEY"]}
        )
    try:
        return _fernet_for(key)
    except (ValueError, TypeError) as exc:
        raise CryptoNotConfiguredError(
            "FERNET_KEY inválida (gere com Fernet.generate_key())"
        ) from exc


def encrypt_token(plaintext: str | None) -> str | None:
    """Cifra um token. None permanece None (conta sem token)."""
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str | None) -> str | None:
    """Decifra um token. None permanece None. Levanta TokenDecryptError se adulterado."""
    if ciphertext is None:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptError("Token criptografado inválido ou adulterado") from exc
