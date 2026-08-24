"""Lógica de consulta/filtragem de campanhas."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, select

from src.extensions import db
from src.models import Campaign, CampaignInfluencer, CampaignStatus, Influencer
from src.utils.errors import NotFoundError


def build_campaign_query(
    agency_id: uuid.UUID,
    *,
    status: CampaignStatus | None = None,
    starts_after: date | None = None,
    ends_before: date | None = None,
    search: str | None = None,
) -> Select:
    """SELECT de campanhas escopado por agência, com filtros de status e período."""
    stmt = (
        select(Campaign)
        .where(Campaign.agency_id == agency_id)
        .order_by(Campaign.period_start.desc())
    )

    if status is not None:
        stmt = stmt.where(Campaign.status == status)
    if starts_after is not None:
        stmt = stmt.where(Campaign.period_start >= starts_after)
    if ends_before is not None:
        stmt = stmt.where(Campaign.period_end <= ends_before)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Campaign.brand_name.ilike(like))

    return stmt


def participants_by_campaign(
    campaign_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict]]:
    """Participantes de várias campanhas em uma query — evita N+1 na listagem.

    Só identidade (id e nome): quem precisa das métricas usa /benchmarking.
    """
    if not campaign_ids:
        return {}

    rows = db.session.execute(
        select(
            CampaignInfluencer.campaign_id,
            Influencer.id,
            Influencer.display_name,
        )
        .join(Influencer, Influencer.id == CampaignInfluencer.influencer_id)
        .where(CampaignInfluencer.campaign_id.in_(campaign_ids))
        .order_by(Influencer.display_name)
    ).all()

    grouped: dict[uuid.UUID, list[dict]] = {cid: [] for cid in campaign_ids}
    for campaign_id, influencer_id, display_name in rows:
        grouped[campaign_id].append(
            {"influencer_id": str(influencer_id), "display_name": display_name}
        )
    return grouped


def validate_participants(participants, agency_id: uuid.UUID) -> None:
    """Confere que todo influencer pedido existe e é da agência.

    Roda ANTES de gravar a campanha: não existe rollback automático aqui, então
    validar depois do INSERT deixaria campanha órfã quando um id fosse inválido.

    Id desconhecido e id de outra agência caem no mesmo 404 — responder coisas
    diferentes revelaria quais ids existem (BOLA).
    """
    if not participants:
        return

    requested = {p.influencer_id for p in participants}
    found = set(
        db.session.scalars(
            select(Influencer.id).where(
                Influencer.id.in_(requested),
                Influencer.agency_id == agency_id,
            )
        ).all()
    )
    if requested - found:
        raise NotFoundError("Influencer não encontrado", code="influencer_not_found")


def attach_participants(campaign: Campaign, participants) -> None:
    """Cria os vínculos. Chame validate_participants antes."""
    for participant in participants:
        db.session.add(
            CampaignInfluencer(
                campaign_id=campaign.id,
                influencer_id=participant.influencer_id,
                fee_brl_cents=participant.fee_brl_cents,
                deliverables=participant.deliverables,
            )
        )
