"""Trabalho que roda depois de a resposta sair.

Existe por causa da enumeração de contas (spec, seção 7): cadastro, reenvio de
verificação e esqueci a senha respondem igual para e-mail que existe e para
e-mail que não existe, e só isso não basta — se um dos ramos grava no banco e
o outro não, o tempo de resposta conta a diferença. Com o Supabase a ~250 ms
por consulta, a diferença é medível a olho. Aqui, a requisição devolve o 202 e
o que difere entre os ramos acontece fora dela.

Nos testes roda na hora, na mesma thread, para a suíte poder conferir o efeito.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from flask import current_app

from src.extensions import db

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lumina-bg")


def em_segundo_plano(funcao: Callable, *args, **kwargs) -> None:
    """Agenda `funcao` com contexto da app. Passe valores simples, nunca objeto do ORM."""
    app = current_app._get_current_object()
    if app.testing:
        funcao(*args, **kwargs)
        return

    def rodar():
        with app.app_context():
            try:
                funcao(*args, **kwargs)
            except Exception:
                logger.exception("Tarefa em segundo plano falhou: %s", funcao.__name__)
                db.session.rollback()
            finally:
                db.session.remove()

    _executor.submit(rodar)
