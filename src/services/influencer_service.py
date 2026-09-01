"""Lógica de consulta/filtragem de influenciadores.

Funções recebem dados já validados e a agency_id de escopo; não tocam Flask request.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import (
    AIAnalysis,
    Influencer,
    InfluencerStatus,
    Platform,
    Post,
    RecommendationDecision,
    RecommendationDecisionKind,
    SocialAccount,
)
from src.utils.errors import NotFoundError, ValidationError


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


# ==========================================================================
# Decisões sobre as recomendações da IA
# ==========================================================================
def _id_de_analise(bruto) -> uuid.UUID:
    """Converte o id que veio do cliente. Malformado é 404, nunca 500.

    A coluna é `Uuid`, e passar a string crua estoura lá dentro com um
    `AttributeError` que vira erro de servidor — o cliente mandou um dado
    ruim e a culpa aparece como nossa.
    """
    try:
        return uuid.UUID(str(bruto))
    except (ValueError, AttributeError, TypeError) as exc:
        raise NotFoundError("Análise não encontrada para este criador") from exc


def registrar_decisao(
    *, influencer: Influencer, analysis_id, item_index: int, decision: str, user
) -> dict:
    """Grava (ou troca) o que a agência decidiu sobre uma recomendação.

    Duas verificações antes de gravar, e as duas existem porque o índice vem do
    cliente: a análise precisa pertencer a **este** criador — senão o id de uma
    análise de outra agência gravaria decisão aqui — e o índice precisa existir
    dentro da lista, senão a decisão aponta para nada e reaparece como órfã
    quando a análise mudar de tamanho.

    Decidir de novo **atualiza** em vez de duplicar: a chave única é
    (análise, índice), e o que interessa é a decisão vigente com quem a tomou.
    """
    analise = db.session.scalar(
        select(AIAnalysis)
        .join(Post, AIAnalysis.post_id == Post.id)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .where(
            AIAnalysis.id == _id_de_analise(analysis_id),
            SocialAccount.influencer_id == influencer.id,
        )
    )
    if analise is None:
        raise NotFoundError("Análise não encontrada para este criador")

    total = len(analise.recommendations or [])
    if not 0 <= item_index < total:
        raise ValidationError(
            f"Recomendação {item_index} não existe nesta análise",
            details={"item_index": item_index, "total": total},
        )

    try:
        tipo = RecommendationDecisionKind(decision)
    except ValueError as exc:
        raise ValidationError(
            "Decisão inválida",
            details={"decision": decision,
                     "aceitos": [k.value for k in RecommendationDecisionKind]},
        ) from exc

    registro = db.session.scalar(
        select(RecommendationDecision).where(
            RecommendationDecision.analysis_id == analise.id,
            RecommendationDecision.item_index == item_index,
        )
    )
    if registro is None:
        registro = RecommendationDecision(analysis_id=analise.id, item_index=item_index)
        db.session.add(registro)
    registro.decision = tipo
    registro.decided_by_user_id = user.id
    db.session.commit()

    return {
        "index": item_index,
        "decision": tipo.value,
        "decided_by": user.name,
        "decided_at": registro.updated_at.isoformat() if registro.updated_at else None,
    }


def desfazer_decisao(*, influencer: Influencer, analysis_id, item_index: int) -> None:
    """Volta a recomendação ao estado indeciso.

    Existe porque decidir por engano é diferente de decidir: sem o desfazer, um
    clique errado congelaria o item para sempre, e a tela ficaria afirmando uma
    decisão que ninguém tomou.
    """
    registro = db.session.scalar(
        select(RecommendationDecision)
        .join(AIAnalysis, RecommendationDecision.analysis_id == AIAnalysis.id)
        .join(Post, AIAnalysis.post_id == Post.id)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .where(
            RecommendationDecision.analysis_id == _id_de_analise(analysis_id),
            RecommendationDecision.item_index == item_index,
            SocialAccount.influencer_id == influencer.id,
        )
    )
    if registro is None:
        raise NotFoundError("Decisão não encontrada")
    db.session.delete(registro)
    db.session.commit()
