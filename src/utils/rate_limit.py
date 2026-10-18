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
_lock = threading.Lock()


class RateLimitExceeded(LuminaError):
    status_code = 429
    code = "rate_limit_exceeded"


MENSAGEM_TENTATIVAS = "Muitas tentativas. Tente novamente em alguns minutos."


def _check(
    key: str, limit: int, window: float, *,
    mensagem: str = "Limite de requisições excedido para esta agência",
    registrar: bool = True,
) -> None:
    now = time.monotonic()
    cutoff = now - window
    with _lock:
        bucket = _buckets[key]
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= limit:
            retry_after = round(window - (now - bucket[0]), 1)
            raise RateLimitExceeded(
                mensagem,
                details={"limit": limit, "window_seconds": window, "retry_after_seconds": retry_after},
            )
        if registrar:
            bucket.append(now)


def reset_rate_limits() -> None:
    """Limpa todos os buckets (usado em testes)."""
    with _lock:
        _buckets.clear()


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
    with _lock:
        _buckets[_chave(config_key, chave)].append(time.monotonic())


def limitar(config_key: str, chave: str) -> None:
    """Confere e conta esta chamada."""
    limit, window = _config(config_key)
    _check(_chave(config_key, chave), limit, window, mensagem=MENSAGEM_TENTATIVAS)


def zerar(config_key: str, chave: str) -> None:
    with _lock:
        _buckets.pop(_chave(config_key, chave), None)


def ip_do_cliente() -> str:
    """Endereço de quem chamou.

    `remote_addr`, e não `X-Forwarded-For`: o cabeçalho é escrito pelo cliente,
    e confiar nele deixaria qualquer um escolher o próprio IP e escapar do
    limite. Atrás de proxy, o certo é configurar `ProxyFix` com o número exato
    de saltos — decisão de implantação, não deste módulo.
    """
    return request.remote_addr or "desconhecido"
