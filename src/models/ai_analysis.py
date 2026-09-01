"""Modelo AIAnalysis — resultado da análise Gemini sobre um post."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models._enums import SentimentLabel
from src.models.base import Base, JSONField, TimestampMixin

if TYPE_CHECKING:
    from src.models.post import Post
    from src.models.recommendation_decision import RecommendationDecision


class AIAnalysis(Base, TimestampMixin):
    """Análise IA de um post. Vários por post (versionamento por modelo)."""

    __tablename__ = "ai_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)

    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)
    sentiment_label: Mapped[SentimentLabel] = mapped_column(
        SAEnum(SentimentLabel, name="sentiment_label"), nullable=False
    )
    script_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brand_coherence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bot_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_phrases: Mapped[Optional[list]] = mapped_column(JSONField, nullable=True)
    recommendations: Mapped[Optional[list]] = mapped_column(JSONField, nullable=True)
    sentiment_breakdown: Mapped[Optional[dict]] = mapped_column(JSONField, nullable=True)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONField, nullable=True)

    post: Mapped["Post"] = relationship(back_populates="ai_analyses")
    recommendation_decisions: Mapped[list["RecommendationDecision"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
