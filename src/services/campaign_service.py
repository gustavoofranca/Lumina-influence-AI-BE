"""Lógica de consulta/filtragem de campanhas."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, select

from src.extensions import db
from src.models import Campaign, CampaignInfluencer, CampaignStatus, Influencer
from src.utils.errors import ConflictError, NotFoundError, ValidationError


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


def add_participant(campaign: Campaign, participant, agency_id: uuid.UUID) -> dict:
    """Vincula um criador à campanha depois que ela já existe.

    Até aqui os participantes só podiam ser escolhidos no momento da criação:
    depois disso a lista era imutável, num produto cuja unidade de trabalho é
    justamente a campanha. Recontratar ou dispensar um criador é a decisão que
    o sistema existe para apoiar.

    A validação é a mesma da criação — id desconhecido e id de outra agência
    caem no mesmo 404, para não revelar quais ids existem.
    """
    validate_participants([participant], agency_id)

    ja_existe = db.session.scalar(
        select(CampaignInfluencer).where(
            CampaignInfluencer.campaign_id == campaign.id,
            CampaignInfluencer.influencer_id == participant.influencer_id,
        )
    )
    if ja_existe is not None:
        # A chave única já barraria, mas com IntegrityError e 500. Conflito
        # explícito é o que permite a interface dizer o que houve.
        raise ConflictError(
            "Criador já vinculado a esta campanha",
            code="participant_already_linked",
        )

    vinculo = CampaignInfluencer(
        campaign_id=campaign.id,
        influencer_id=participant.influencer_id,
        fee_brl_cents=participant.fee_brl_cents,
        deliverables=participant.deliverables,
    )
    db.session.add(vinculo)
    db.session.commit()

    criador = db.session.get(Influencer, participant.influencer_id)
    return {
        "influencer_id": str(participant.influencer_id),
        "display_name": criador.display_name if criador else None,
        "fee_brl_cents": vinculo.fee_brl_cents,
    }


def remove_participant(campaign: Campaign, influencer_id: uuid.UUID) -> None:
    """Desvincula o criador da campanha.

    Apaga **só o vínculo**: o criador continua cadastrado, e as publicações
    dele continuam existindo. Sair de uma campanha não é deixar de existir — e
    o `campaign_id` do post é `SET NULL`, não cascade, justamente por isso.
    """
    vinculo = db.session.scalar(
        select(CampaignInfluencer).where(
            CampaignInfluencer.campaign_id == campaign.id,
            CampaignInfluencer.influencer_id == influencer_id,
        )
    )
    if vinculo is None:
        raise NotFoundError("Criador não está vinculado a esta campanha")
    db.session.delete(vinculo)
    db.session.commit()


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


def create_campaign(*, agency_id: uuid.UUID, payload, participants) -> Campaign:
    """Cria a campanha e os vínculos numa transação.

    Os participantes já vêm validados: gravar antes de validar deixaria
    campanha órfã quando um influencer fosse inválido.
    """
    camp = Campaign(
        agency_id=agency_id,
        brand_name=payload.brand_name,
        title=payload.title,
        period_start=payload.period_start,
        period_end=payload.period_end,
        budget_brl_cents=payload.budget_brl_cents,
        status=payload.status,
    )
    db.session.add(camp)
    db.session.flush()

    attach_participants(camp, participants)
    db.session.commit()
    return camp


def apply_update(campaign: Campaign, data: dict) -> Campaign:
    """Aplica o PATCH validando o período resultante do merge."""
    new_start = data.get("period_start", campaign.period_start)
    new_end = data.get("period_end", campaign.period_end)
    if new_end < new_start:
        raise ValidationError("period_end não pode ser anterior a period_start")

    for field, value in data.items():
        setattr(campaign, field, value)
    db.session.commit()
    return campaign


def delete_campaign(campaign: Campaign) -> None:
    db.session.delete(campaign)
    db.session.commit()
