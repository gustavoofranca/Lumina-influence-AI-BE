"""Verificação de dependências externas para o healthcheck."""
from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.extensions import db

logger = logging.getLogger(__name__)


def database_connected() -> bool:
    """Toca o banco de verdade — um ping que não abre conexão não prova nada."""
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("healthcheck: db indisponível: %s", exc.__class__.__name__)
        return False


# Ambientes em que o compromisso publicado vale para gente de verdade. Em dev e
# em teste o free tier é aceitável: os dados são de seed.
AMBIENTES_COM_USUARIO_REAL = ("staging", "prod")


def privacidade_do_modelo_conforme() -> bool:
    """A configuração do Gemini bate com o que a política de privacidade afirma?

    A política diz que os dados enviados não são usados para treinar modelo.
    Isso é verdade no tier pago da API do Gemini e **não** é no free tier, onde
    o Google pode usar o conteúdo para melhorar seus produtos. A diferença não
    é detectável pela chave, então depende de `GEMINI_PAID_TIER` ser declarado.

    Exposto no healthcheck de propósito: um compromisso com o usuário que
    depende de configuração precisa ser visível em operação, não só no boot.
    """
    if current_app.config.get("ENV") not in AMBIENTES_COM_USUARIO_REAL:
        return True
    if not current_app.config.get("GEMINI_API_KEY"):
        # Sem chave não há envio ao modelo, e não há o que prometer.
        return True
    return bool(current_app.config.get("GEMINI_PAID_TIER"))


def avisar_se_privacidade_do_modelo_nao_confere(app) -> None:
    """Reclama alto no boot. Chamado pela fábrica da aplicação."""
    with app.app_context():
        if privacidade_do_modelo_conforme():
            return
    logger.warning(
        "[privacidade] GEMINI_PAID_TIER não declarado em %s: no free tier o Google "
        "pode usar o conteúdo enviado para melhorar seus produtos, o que contradiz "
        "a Política de Privacidade publicada. Habilite o faturamento no AI Studio e "
        "defina GEMINI_PAID_TIER=true, ou remova a afirmação do documento.",
        app.config.get("ENV"),
    )
