"""Rate limit simples in-memory (janela deslizante) por agência.

Escolha consciente do TCC: sem Redis. Para um monolito de instância única, um
contador in-process basta. Em produção multi-instância, trocar por um store
compartilhado (Redis). Ver ADR (decisão APScheduler/sem Redis).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Callable

from flask import current_app, request

from src.utils.authz import current_agency_id
from src.utils.errors import LuminaError

_buckets: dict[str, list[float]] = defaultdict(list)
# Janela de cada chave, guardada na hora de registrar: a varredura global precisa
# saber quando os registros de uma chave que ninguém mais toca já expiraram.
_janelas: dict[str, float] = {}
_gravacoes = 0
# A cada tantas gravações, varre tudo. Chaves de login vêm do cliente (e-mail e IP
# escolhidos por quem ataca); sem varredura, um e-mail aleatório por tentativa
# deixaria uma entrada para sempre na memória (DoS lento, spec seção 7).
_VARRER_A_CADA = 256
_lock = threading.Lock()


class RateLimitExceeded(LuminaError):
    status_code = 429
    code = "rate_limit_exceeded"


MENSAGEM_TENTATIVAS = "Muitas tentativas. Tente novamente em alguns minutos."


def _varrer_expirados(now: float) -> None:
    """Remove timestamps vencidos de todas as chaves e apaga as que esvaziaram.

    Chamar com `_lock` já seguro.
    """
    for key in list(_buckets):
        janela = _janelas.get(key)
        bucket = _buckets[key]
        if janela is not None:
            cutoff = now - janela
            bucket[:] = [t for t in bucket if t > cutoff]
        if not bucket:
            del _buckets[key]
            _janelas.pop(key, None)


def _gravar(key: str, window: float, now: float) -> None:
    """Registra um timestamp e dispara a varredura periódica. Exige `_lock`."""
    global _gravacoes
    _buckets[key].append(now)
    _janelas[key] = window
    _gravacoes += 1
    if _gravacoes >= _VARRER_A_CADA:
        _gravacoes = 0
        _varrer_expirados(now)


def _check(
    key: str, limit: int, window: float, *,
    mensagem: str = "Limite de requisições excedido para esta agência",
    registrar: bool = True,
) -> None:
    now = time.monotonic()
    cutoff = now - window
    with _lock:
        # `.get`: só conferir não pode criar a chave (o defaultdict criaria).
        bucket = [t for t in _buckets.get(key, ()) if t > cutoff]
        if not bucket:
            # Esvaziou pela poda: apaga a chave em vez de deixá-la vazia.
            _buckets.pop(key, None)
            _janelas.pop(key, None)
        else:
            _buckets[key][:] = bucket
        if len(bucket) >= limit:
            retry_after = round(window - (now - bucket[0]), 1)
            raise RateLimitExceeded(
                mensagem,
                details={"limit": limit, "window_seconds": window, "retry_after_seconds": retry_after},
            )
        if registrar:
            _gravar(key, window, now)


def reset_rate_limits() -> None:
    """Limpa todos os buckets (usado em testes)."""
    global _gravacoes
    with _lock:
        _buckets.clear()
        _janelas.clear()
        _gravacoes = 0


def rate_limit(config_key: str, *, default_limit: int = 30, default_window: float = 60) -> Callable:
    """Decorator: limita chamadas por agência. Lê {limit, window} de app.config[config_key].

    Deve rodar DEPOIS de @require_auth (precisa de g.current_user / agência).
    """

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            cfg = current_app.config.get(config_key) or {}
            limit = int(cfg.get("limit", default_limit))
            window = float(cfg.get("window", default_window))
            key = f"{config_key}:{current_agency_id()}"
            _check(key, limit, window)
            return view(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Limite por chave arbitrária — autenticação, onde ainda não há agência
# --------------------------------------------------------------------------
def _config(config_key: str) -> tuple[int, float]:
    cfg = current_app.config[config_key]
    return int(cfg["limit"]), float(cfg["window"])


def _chave(config_key: str, chave: str) -> str:
    return f"{config_key}:{chave}"


def conferir_limite(config_key: str, chave: str) -> None:
    """Levanta 429 se a chave já estourou. Não conta esta chamada."""
    limit, window = _config(config_key)
    _check(_chave(config_key, chave), limit, window, mensagem=MENSAGEM_TENTATIVAS, registrar=False)


def registrar_tentativa(config_key: str, chave: str) -> None:
    _, window = _config(config_key)
    with _lock:
        _gravar(_chave(config_key, chave), window, time.monotonic())


def limitar(config_key: str, chave: str) -> None:
    """Confere e conta esta chamada."""
    limit, window = _config(config_key)
    _check(_chave(config_key, chave), limit, window, mensagem=MENSAGEM_TENTATIVAS)


def zerar(config_key: str, chave: str) -> None:
    with _lock:
        k = _chave(config_key, chave)
        _buckets.pop(k, None)
        _janelas.pop(k, None)


def ip_do_cliente() -> str:
    """Endereço de quem chamou.

    `remote_addr`, e não `X-Forwarded-For`: o cabeçalho é escrito pelo cliente,
    e confiar nele deixaria qualquer um escolher o próprio IP e escapar do
    limite. Atrás de proxy, `TRUSTED_PROXIES` liga o `ProxyFix` em `create_app`
    com o número exato de saltos, e `remote_addr` passa a ser o IP real.
    """
    return request.remote_addr or "desconhecido"
