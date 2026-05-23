"""Enums do domínio. Mapeiam pra ENUM nativo no Postgres e VARCHAR+CHECK em SQLite."""
from __future__ import annotations

import enum


class OAuthProvider(str, enum.Enum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Platform(str, enum.Enum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


class InfluencerStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"


class PostType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    REEL = "reel"
    STORY = "story"
    SHORT = "short"
    CAROUSEL = "carousel"


class SentimentLabel(str, enum.Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class ReportFormat(str, enum.Enum):
    PDF = "pdf"
    JSON = "json"
