"""Consulta de posts e do histórico de análises, escopado por agência."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import AIAnalysis, Post
from src.services import social_account_service
from src.utils.errors import NotFoundError


def load_scoped_post(post_id, agency_id: uuid.UUID) -> Post:
    """Post da agência ou 404.

    Post não tem agency_id próprio: o que impede ler post de outro cliente é
    a conta social dele estar entre as da agência. Quais contas são da agência
    é o domínio de Criadores que diz (ADR-008), por isso o filtro usa a
    subconsulta dele em vez de refazer o join com SocialAccount e Influencer.
    """
    try:
        pid = uuid.UUID(str(post_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("Post não encontrado") from exc

    post = db.session.scalar(
        select(Post)
        .where(
            Post.id == pid,
            Post.social_account_id.in_(social_account_service.contas_da_agencia(agency_id)),
        )
        # O criador (nicho, lido pela análise de IA) vem por lazy load ao ser
        # acessado: encadear `.selectinload(SocialAccount.influencer)` exigiria
        # importar o model de Criadores. Para um post só, dá a mesma consulta
        # a mais que o selectinload faria.
        .options(selectinload(Post.social_account))
    )
    if post is None:
        raise NotFoundError("Post não encontrado")
    return post


def list_analyses(post_id: uuid.UUID) -> list[AIAnalysis]:
    """Histórico de análises do post, mais recente primeiro."""
    return list(db.session.scalars(
        select(AIAnalysis)
        .where(AIAnalysis.post_id == post_id)
        .order_by(AIAnalysis.analyzed_at.desc())
    ).all())
