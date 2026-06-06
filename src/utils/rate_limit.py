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

from flask import current_app

from src.utils.authz import current_agency_id
from src.utils.errors import LuminaError

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()


class RateLimitExceeded(LuminaError):
    status_code = 429
    code = "rate_limit_exceeded"


def _check(key: str, limit: int, window: float) -> None:
    now = time.monotonic()
    cutoff = now - window
    with _lock:
        bucket = _buckets[key]
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= limit:
            retry_after = round(window - (now - bucket[0]), 1)
            raise RateLimitExceeded(
                "Limite de requisições excedido para esta agência",
                details={"limit": limit, "window_seconds": window, "retry_after_seconds": retry_after},
            )
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
