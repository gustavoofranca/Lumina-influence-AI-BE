"""Modelo RecommendationDecision — o que a agência decidiu sobre cada recomendação."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import RecommendationDecisionKind
from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.ai_analysis import AIAnalysis
    from src.models.user import User


class RecommendationDecision(Base, TimestampMixin):
    """Aceite ou descarte de uma recomendação da IA, com autoria.

    A recomendação não é uma linha própria: ela vive dentro do JSON da análise,
    que é imutável depois de gerada. A identidade estável de um item é, então,
    o par **(análise, posição na lista)** — e é isso que a chave única fixa.

    Guardar a decisão importa por dois motivos, e o segundo é o que justifica
    a autoria: sem persistir, a tela mentia (o estado sumia ao recarregar, e
    "aceito" nunca tinha acontecido de verdade); e uma auditoria em que ninguém
    responde por ter aceitado uma recomendação não é auditoria.
    """

    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "item_index", name="uq_recommendation_decision_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[RecommendationDecisionKind] = mapped_column(
        SAEnum(RecommendationDecisionKind, name="recommendation_decision"), nullable=False
    )
    # `SET NULL`, e não cascade: a decisão continua valendo depois que quem a
    # tomou sai da agência. Apagar o registro reescreveria o histórico.
    decided_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    analysis: Mapped["AIAnalysis"] = relationship(back_populates="recommendation_decisions")
    decided_by: Mapped[Optional["User"]] = relationship()
