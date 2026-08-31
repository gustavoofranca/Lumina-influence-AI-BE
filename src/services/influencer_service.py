"""Lógica de consulta/filtragem de influenciadores.

Funções recebem dados já validados e a agency_id de escopo; não tocam Flask request.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import Influencer, InfluencerStatus, Platform, SocialAccount


def build_influencer_query(
    agency_id: uuid.UUID,
    *,
    search: str | None = None,
    status: InfluencerStatus | None = None,
    platform: Platform | None = None,
    follower_min: int | None = None,
    follower_max: int | None = None,
) -> Select:
    """Monta o SELECT de influenciadores com filtros, escopado por agência.

    - `platform`: exige uma social_account naquela plataforma (EXISTS).
    - `follower_min/max`: filtra pela SOMA de follower_count das contas (HAVING).
    - `search`: ILIKE em display_name ou niche.
    """
    stmt = (
        select(Influencer)
        .where(Influencer.agency_id == agency_id)
        .options(selectinload(Influencer.social_accounts))
        .order_by(Influencer.display_name.asc())
    )

    if status is not None:
        stmt = stmt.where(Influencer.status == status)

    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(Influencer.display_name.ilike(like), Influencer.niche.ilike(like))
        )

    if platform is not None:
        stmt = stmt.where(
            Influencer.social_accounts.any(SocialAccount.platform == platform)
        )

    if follower_min is not None or follower_max is not None:
        # Subquery: soma de seguidores por influencer.
        sums = (
            select(
                SocialAccount.influencer_id.label("inf_id"),
                func.coalesce(func.sum(SocialAccount.follower_count), 0).label("total"),
            )
            .group_by(SocialAccount.influencer_id)
            .subquery()
        )
        # LEFT JOIN, não INNER: criador ainda sem conta conectada tem zero
        # seguidor, e zero pertence à faixa "menos de 100k". Com o join interno
        # ele sumia da listagem filtrada — justamente quem acabou de ser
        # cadastrado e precisa ser conectado.
        total = func.coalesce(sums.c.total, 0)
        stmt = stmt.outerjoin(sums, sums.c.inf_id == Influencer.id)
        if follower_min is not None:
            stmt = stmt.where(total >= follower_min)
        if follower_max is not None:
            stmt = stmt.where(total <= follower_max)

    return stmt


def create_influencer(
    *,
    agency_id: uuid.UUID,
    display_name: str,
    niche: str | None,
    bio: str | None,
    status: InfluencerStatus,
) -> Influencer:
    inf = Influencer(
        agency_id=agency_id,
        display_name=display_name,
        niche=niche,
        bio=bio,
        status=status,
    )
    db.session.add(inf)
    db.session.commit()
    return inf


def apply_update(influencer: Influencer, data: dict) -> Influencer:
    for field, value in data.items():
        setattr(influencer, field, value)
    db.session.commit()
    return influencer


def delete_influencer(influencer: Influencer) -> None:
    """Delete físico — cascade leva contas sociais e posts. Não há soft delete."""
    db.session.delete(influencer)
    db.session.commit()
