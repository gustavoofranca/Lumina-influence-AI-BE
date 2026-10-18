"""Consulta de CNPJ na BrasilAPI (dados públicos da Receita Federal).

Regra de ouro: a consulta **nunca** trava o cadastro por estar indisponível. Ela
só recusa quando responde, com certeza, que a empresa está NULA, SUSPENSA,
INAPTA ou BAIXADA. "Não encontrado" não é recusa — o CNPJ alfanumérico recém-
emitido ainda não está na base dela (medido em 15/10/2026: `12ABC34501DE35`
devolve 404) —, e timeout ou erro também não.

Só `razao_social` e a situação saem daqui. A resposta da BrasilAPI traz também
o quadro de sócios, com nome e parte do CPF de pessoas físicas, e esse dado
não tem uso no produto (LGPD, princípio da necessidade).

Antes de montar a URL, o CNPJ precisa casar o formato exato — 14 caracteres em
`[0-9A-Z]` —, para que nenhuma entrada consiga alterar o caminho requisitado
(SSRF).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import requests
from flask import current_app

from src.schemas.campos import CNPJ_CRU, cnpj_cru

logger = logging.getLogger(__name__)

URL = "https://brasilapi.com.br/api/cnpj/v1/{}"
TIMEOUT_SEGUNDOS = 5
_CACHE_SEGUNDOS = 24 * 3600
_CACHE_MAXIMO = 1000
_SITUACOES_IMPEDITIVAS = {1, 3, 4, 8}  # NULA, SUSPENSA, INAPTA, BAIXADA


@dataclass(frozen=True)
class ConsultaCnpj:
    encontrado: bool
    razao_social: str | None
    situacao: str | None
    impeditiva: bool


NAO_CONSULTADO = ConsultaCnpj(False, None, None, False)

_cache: dict[str, tuple[float, ConsultaCnpj]] = {}
_lock = threading.Lock()


def limpar_cache() -> None:
    with _lock:
        _cache.clear()


def _do_cache(cru: str) -> ConsultaCnpj | None:
    with _lock:
        item = _cache.get(cru)
        if item and time.monotonic() - item[0] < _CACHE_SEGUNDOS:
            return item[1]
    return None


def _guardar(cru: str, consulta: ConsultaCnpj) -> None:
    with _lock:
        if len(_cache) >= _CACHE_MAXIMO:
            _cache.pop(next(iter(_cache)))
        _cache[cru] = (time.monotonic(), consulta)


def consultar_cnpj(cnpj: str) -> ConsultaCnpj:
    if not current_app.config.get("CNPJ_CONSULTA_ENABLED"):
        return NAO_CONSULTADO
    cru = cnpj_cru(cnpj or "")
    if not CNPJ_CRU.fullmatch(cru):
        return NAO_CONSULTADO
    guardada = _do_cache(cru)
    if guardada is not None:
        return guardada
    try:
        resposta = requests.get(URL.format(cru), timeout=TIMEOUT_SEGUNDOS,
                                headers={"User-Agent": "Lumina/0.1"})
    except requests.RequestException:
        logger.warning("BrasilAPI indisponível; CNPJ segue só pelo dígito verificador")
        return NAO_CONSULTADO
    if resposta.status_code == 404:
        consulta = ConsultaCnpj(False, None, None, False)
    elif resposta.status_code != 200:
        logger.warning("BrasilAPI respondeu %s; CNPJ segue só pelo DV", resposta.status_code)
        return NAO_CONSULTADO
    else:
        dados = resposta.json()
        consulta = ConsultaCnpj(
            encontrado=True,
            razao_social=dados.get("razao_social"),
            situacao=dados.get("descricao_situacao_cadastral"),
            impeditiva=dados.get("situacao_cadastral") in _SITUACOES_IMPEDITIVAS,
        )
    _guardar(cru, consulta)
    return consulta
