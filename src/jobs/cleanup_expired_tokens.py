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
from sqlalchemy import or_, select

from src.extensions import db, scheduler
from src.models import ApiUsageLog, AuthToken, SocialAccount, User
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


def purge_unverified_accounts(dias: int) -> int:
    """Cadastro por senha que ninguém confirmou em `dias` dias.

    Vai a agência inteira quando o cadastro é o único membro dela — é o caso
    normal, porque a agência nasceu com ele e ninguém consegue entrar nela sem
    confirmar o e-mail.
    """
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    pendentes = db.session.scalars(
        select(User).where(
            User.password_hash.is_not(None),
            User.email_verificado_em.is_(None),
            User.created_at < corte,
        )
    ).all()
    for user in pendentes:
        agencia = user.agency
        sozinho = agencia is not None and all(u.id == user.id for u in agencia.users)
        db.session.delete(agencia if sozinho else user)
    return len(pendentes)


def purge_spent_auth_tokens() -> int:
    """Token usado, ou vencido há mais de um dia: não serve para mais nada."""
    corte = datetime.now(timezone.utc) - timedelta(days=1)
    return (
        db.session.query(AuthToken)
        .filter(or_(AuthToken.usado_em.is_not(None), AuthToken.expira_em < corte))
        .delete(synchronize_session=False)
    )


def run_cleanup_expired_tokens() -> dict:
    """Lógica do job (assume app context ativo)."""
    dias = current_app.config.get("RETENTION_DAYS", 90)
    dias_pendentes = current_app.config.get("CONTAS_NAO_VERIFICADAS_DIAS", 7)
    removidos = cleanup_expired_oauth_states()
    tokens = purge_dead_social_tokens()
    logs = purge_old_usage_logs(dias)
    tokens_auth = purge_spent_auth_tokens()
    pendentes = purge_unverified_accounts(dias_pendentes)
    db.session.commit()
    logger.info(
        "cleanup: %d oauth_states, %d tokens mortos, %d registros de uso (>%dd), "
        "%d tokens de e-mail, %d cadastros não confirmados",
        removidos, tokens, logs, dias, tokens_auth, pendentes,
    )
    return {
        "removed": removidos,
        "dead_tokens_purged": tokens,
        "usage_logs_purged": logs,
        "retention_days": dias,
        "auth_tokens_purged": tokens_auth,
        "unverified_accounts_purged": pendentes,
    }


def cleanup_expired_tokens_job() -> None:
    """Entrypoint chamado pelo APScheduler (cria app context)."""
    with scheduler.app.app_context():
        try:
            run_cleanup_expired_tokens()
        except Exception:
            logger.exception("cleanup_expired_tokens falhou")
            db.session.rollback()
