"""Schemas de Post e AIAnalysis (saída)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class AIAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    post_id: uuid.UUID
    analyzed_at: datetime
    model_version: str
    sentiment_score: float
    sentiment_label: str
    script_score: Optional[float] = None
    brand_coherence_score: Optional[float] = None
    bot_probability: Optional[float] = None
    transcript_text: Optional[str] = None
    key_phrases: Optional[list] = None
    recommendations: Optional[list] = None
    sentiment_breakdown: Optional[dict] = None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    social_account_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    platform_post_id: str
    post_type: str
    posted_at: datetime
    caption: Optional[str] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    reach_total: int
    reach_organic: int
    reach_paid: int
    impressions: int
    likes: int
    comments_count: int
    shares: int
    saves: int
    avg_watch_time: Optional[float] = None
    retention_rate: Optional[float] = None
