"""Política e hash de senha.

Política: NIST SP 800-63B rev. 4. Comprimento em vez de regra de composição
(exigir maiúscula e símbolo produz "Senha@123", que está em toda lista de
vazamento), recusa de senha vazada e de senha montada com dado da própria
pessoa. Nada de troca periódica obrigatória.

Hash: Argon2id, primeira escolha do OWASP Password Storage Cheat Sheet, com os
parâmetros padrão do `argon2-cffi` (perfil de baixa memória da RFC 9106, acima
do mínimo do OWASP). `precisa_rehash` permite subir o custo depois sem forçar
ninguém a trocar de senha: o hash é refeito no próximo login.

A lista de vazadas é o `Pwdb_top-1000000.txt` do SecLists (licença MIT),
filtrado para 12 a 128 caracteres, em minúsculas, sem repetição. A lista de 10
mil mais comuns foi descartada: só 10 das suas senhas têm 12 caracteres ou
mais. Para regerar, ver a Tarefa A2 do plano de 15/10/2026.
"""
from __future__ import annotations

import gzip
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_CARACTERES = 12
MAX_CARACTERES = 128

_LISTA = Path(__file__).with_name("senhas_comuns.txt.gz")
_hasher = PasswordHasher()


def normalizar(senha: str) -> str:
    """NFKC, como o NIST recomenda: a mesma senha digitada em teclados
    diferentes chega com bytes diferentes ("é" composto ou "e" + acento)."""
    return unicodedata.normalize("NFKC", senha)


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").lower()


@lru_cache(maxsize=1)
def _comuns() -> frozenset[str]:
    with gzip.open(_LISTA, "rt", encoding="utf-8") as f:
        return frozenset(linha.strip() for linha in f if linha.strip())


def problema_da_senha(
    senha: str, *, email: str | None = None, nome: str | None = None
) -> str | None:
    """A frase que explica a recusa, ou None. Sem sujeito: o rótulo do campo vem antes."""
    s = normalizar(senha)
    if len(s) < MIN_CARACTERES:
        return f"deve ter pelo menos {MIN_CARACTERES} caracteres"
    if len(s) > MAX_CARACTERES:
        return f"deve ter no máximo {MAX_CARACTERES} caracteres"
    if len(set(s)) == 1:
        return "é previsível demais"
    if s.lower() in _comuns():
        return "é muito comum — aparece em vazamentos de senha"
    alvo = _sem_acento(s)
    local = _sem_acento((email or "").split("@")[0])
    if len(local) >= 4 and local in alvo:
        return "não use seu e-mail na senha"
    for palavra in re.findall(r"[^\W\d_]+", _sem_acento(nome or "")):
        if len(palavra) >= 4 and palavra in alvo:
            return "não use seu nome na senha"
    return None


def gerar_hash(senha: str) -> str:
    return _hasher.hash(normalizar(senha))


def conferir(senha: str, hash_gravado: str) -> bool:
    try:
        return _hasher.verify(hash_gravado, normalizar(senha))
    except (VerificationError, InvalidHashError):
        return False


def precisa_rehash(hash_gravado: str) -> bool:
    return _hasher.check_needs_rehash(hash_gravado)


@lru_cache(maxsize=1)
def _hash_ficticio() -> str:
    return _hasher.hash("senha-ficticia-que-ninguem-usa-para-tempo-constante")


def conferir_contra_hash_ficticio(senha: str) -> None:
    """Gasta o mesmo tempo de uma verificação real.

    Sem isto, o login de e-mail inexistente responderia mais rápido que o de
    senha errada, e o tempo diria quem tem conta.
    """
    conferir(senha, _hash_ficticio())
