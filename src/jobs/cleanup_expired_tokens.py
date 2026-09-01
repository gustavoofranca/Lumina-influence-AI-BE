"""Job: higiene diária de credencial morta e de registro técnico vencido.

O que este job apaga é **declarado na Política de Privacidade publicada** —
"tokens de acesso expirados são removidos automaticamente pela rotina de
limpeza" e "registros técnicos são descartados em até 90 dias". Mexer no que
ele faz, ou no prazo, muda um compromisso com o usuário, não só uma rotina.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select

from src.extensions import db, scheduler
from src.models import ApiUsageLog, SocialAccount
from src.services.auth_service import cleanup_expired_oauth_states

logger = logging.getLogger("lumina.jobs.cleanup_expired_tokens")


def purge_dead_social_tokens() -> int:
    """Apaga token de acesso expirado que já não pode ser renovado.

    A condição é a mesma que `_valid_access_token` usa para decidir se vale
    tentar renovar: sem `refresh_token`, um token vencido é credencial morta —
    a próxima coleta levaria 401 e o sistema o apagaria de qualquer forma. Até
    lá ele fica em repouso sem servir para nada, e credencial guardada sem uso
    é superfície de risco sem contrapartida.

    Contas com refresh token **não são tocadas**: ali o vencimento é rotina, e
    apagar quebraria uma conexão que funciona.
    """
    agora = datetime.now(timezone.utc)
    contas = db.session.scalars(
        select(SocialAccount).where(
            SocialAccount.access_token_encrypted.is_not(None),
            SocialAccount.refresh_token_encrypted.is_(None),
            SocialAccount.token_expires_at.is_not(None),
            SocialAccount.token_expires_at < agora,
        )
    ).all()
    for conta in contas:
        conta.access_token_encrypted = None
        conta.token_expires_at = None
    return len(contas)


def purge_old_usage_logs(retention_days: int) -> int:
    """Descarta o log de uso de API mais velho que a janela de retenção.

    É o único registro técnico que o produto **guarda em banco**; o resto vai
    para a saída padrão e é retido pelo ambiente, não por nós. A distinção está
    escrita na política, porque prometer descarte de algo que não controlamos
    seria promessa vazia.
    """
    corte = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return (
        db.session.query(ApiUsageLog)
        .filter(ApiUsageLog.called_at < corte)
        .delete(synchronize_session=False)
    )


def run_cleanup_expired_tokens() -> dict:
    """Lógica do job (assume app context ativo)."""
    dias = current_app.config.get("RETENTION_DAYS", 90)
    removidos = cleanup_expired_oauth_states()
    tokens = purge_dead_social_tokens()
    logs = purge_old_usage_logs(dias)
    db.session.commit()
    logger.info(
        "cleanup: %d oauth_states, %d tokens mortos, %d registros de uso (>%dd)",
        removidos, tokens, logs, dias,
    )
    return {
        "removed": removidos,
        "dead_tokens_purged": tokens,
        "usage_logs_purged": logs,
        "retention_days": dias,
    }


def cleanup_expired_tokens_job() -> None:
    """Entrypoint chamado pelo APScheduler (cria app context)."""
    with scheduler.app.app_context():
        try:
            run_cleanup_expired_tokens()
        except Exception:
            logger.exception("cleanup_expired_tokens falhou")
            db.session.rollback()
