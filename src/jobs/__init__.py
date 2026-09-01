"""Registro central dos background jobs (B7).

`JOB_DEFINITIONS` descreve cada job: id, referência string da função (necessária
pro jobstore SQLAlchemy persistir), trigger, e a função de lógica síncrona usada
pelo CLI `flask jobs run <name>`.
"""
from __future__ import annotations

import logging

from src.jobs.cleanup_expired_tokens import run_cleanup_expired_tokens
from src.jobs.run_pending_analyses import run_pending_analyses
from src.jobs.sync_metrics import run_sync_metrics

logger = logging.getLogger("lumina.jobs")

JOB_DEFINITIONS = [
    {
        "id": "sync_metrics",
        "func": "src.jobs.sync_metrics:sync_metrics_job",
        "trigger": "interval",
        "trigger_kwargs": {"hours": 6},
        "logic": run_sync_metrics,
        "description": "Sincroniza métricas dos posts dos últimos 7 dias (a cada 6h).",
    },
    {
        "id": "run_pending_analyses",
        "func": "src.jobs.run_pending_analyses:run_pending_analyses_job",
        "trigger": "interval",
        "trigger_kwargs": {"minutes": 30},
        "logic": run_pending_analyses,
        "description": "Processa posts marcados como needs_analysis via Gemini (a cada 30min).",
    },
    {
        "id": "cleanup_expired_tokens",
        "func": "src.jobs.cleanup_expired_tokens:cleanup_expired_tokens_job",
        "trigger": "interval",
        "trigger_kwargs": {"days": 1},
        "logic": run_cleanup_expired_tokens,
        "description": "Higiene diária: states OAuth expirados, tokens mortos e registros de uso fora da janela de retenção.",
    },
]

_BY_ID = {d["id"]: d for d in JOB_DEFINITIONS}


def register_jobs(scheduler) -> None:
    """Adiciona/atualiza os jobs no scheduler. Idempotente (replace_existing)."""
    for d in JOB_DEFINITIONS:
        scheduler.add_job(
            id=d["id"],
            func=d["func"],
            trigger=d["trigger"],
            replace_existing=True,
            **d["trigger_kwargs"],
        )
        logger.info("Job registrado: %s (%s)", d["id"], d["trigger_kwargs"])


def list_jobs() -> list[dict]:
    return [
        {
            "id": d["id"],
            "trigger": d["trigger"],
            "schedule": d["trigger_kwargs"],
            "description": d["description"],
        }
        for d in JOB_DEFINITIONS
    ]


def run_job_by_name(name: str) -> dict:
    """Executa a lógica de um job sincronamente (usado pelo CLI). Assume app context."""
    if name not in _BY_ID:
        raise KeyError(name)
    return _BY_ID[name]["logic"]()
