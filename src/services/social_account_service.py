"""Contas sociais — escopo vem do Influencer dono, não da própria conta."""
from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from src.extensions import db
from src.models import Influencer, Platform, SocialAccount
from src.utils.errors import ConflictError, NotFoundError


def build_account_query(
    agency_id: uuid.UUID, *, influencer_id: str | None = None
) -> Select:
    """SELECT das contas da agência, mais recentes primeiro.

    O join com Influencer é o que escopa: SocialAccount não tem agency_id.
    """
    stmt = (
        select(SocialAccount)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Influencer.agency_id == agency_id)
        .order_by(SocialAccount.created_at.desc())
    )
    if influencer_id:
        try:
            stmt = stmt.where(SocialAccount.influencer_id == uuid.UUID(influencer_id))
        except ValueError:
            # Id malformado não é erro de requisição: filtra para conjunto vazio.
            stmt = stmt.where(SocialAccount.influencer_id == uuid.uuid4())
    return stmt


def load_scoped_account(account_id, agency_id: uuid.UUID) -> SocialAccount:
    try:
        sid = uuid.UUID(str(account_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("SocialAccount não encontrada") from exc

    sa = db.session.scalar(
        select(SocialAccount)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(SocialAccount.id == sid, Influencer.agency_id == agency_id)
    )
    if sa is None:
        raise NotFoundError("SocialAccount não encontrada")
    return sa


def create_account(
    *,
    influencer_id: uuid.UUID,
    platform: Platform,
    handle: str,
    platform_user_id: str | None,
    follower_count: int,
) -> SocialAccount:
    """Cria a conta. O trio influencer/plataforma/handle é único."""
    dup = db.session.scalar(
        select(SocialAccount).where(
            SocialAccount.influencer_id == influencer_id,
            SocialAccount.platform == platform,
            SocialAccount.handle == handle,
        )
    )
    if dup is not None:
        raise ConflictError(
            "Conta já cadastrada para este influencer/plataforma/handle",
            code="social_account_exists",
        )

    sa = SocialAccount(
        influencer_id=influencer_id,
        platform=platform,
        handle=handle,
        platform_user_id=platform_user_id,
        follower_count=follower_count,
    )
    db.session.add(sa)
    db.session.commit()
    return sa


def apply_update(account: SocialAccount, data: dict) -> SocialAccount:
    for field, value in data.items():
        setattr(account, field, value)
    db.session.commit()
    return account


def delete_account(account: SocialAccount) -> None:
    db.session.delete(account)
    db.session.commit()
