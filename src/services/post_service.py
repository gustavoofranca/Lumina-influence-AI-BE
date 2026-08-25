"""Consulta de posts e do histórico de análises, escopado por agência."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import AIAnalysis, Influencer, Post, SocialAccount
from src.utils.errors import NotFoundError


def load_scoped_post(post_id, agency_id: uuid.UUID) -> Post:
    """Post da agência ou 404.

    O escopo passa por social_account -> influencer -> agency: Post não tem
    agency_id próprio, então o join é o que impede ler post de outro cliente.
    """
    try:
        pid = uuid.UUID(str(post_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("Post não encontrado") from exc

    post = db.session.scalar(
        select(Post)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Post.id == pid, Influencer.agency_id == agency_id)
        .options(selectinload(Post.social_account).selectinload(SocialAccount.influencer))
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
