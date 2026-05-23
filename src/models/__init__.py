"""Re-exporta todos os models pra que `Base.metadata` veja as tabelas.

Importante: este módulo precisa ser importado em algum lugar do bootstrap
do app (via `src.app`) pra que o Alembic autogenerate enxergue tudo.
"""
from src.models._enums import (
    CampaignStatus,
    InfluencerStatus,
    OAuthProvider,
    Platform,
    PostType,
    ReportFormat,
    SentimentLabel,
    UserRole,
)
from src.models.agency import Agency, Plan
from src.models.ai_analysis import AIAnalysis
from src.models.api_usage import ApiUsageLog
from src.models.base import Base, JSONField, SoftDeleteMixin, TimestampMixin
from src.models.campaign import Campaign, CampaignInfluencer
from src.models.influencer import Influencer
from src.models.oauth_state import OAuthState
from src.models.post import Comment, Post
from src.models.report import Report
from src.models.social_account import SocialAccount
from src.models.user import User

__all__ = [
    "Base",
    "JSONField",
    "SoftDeleteMixin",
    "TimestampMixin",
    "CampaignStatus",
    "InfluencerStatus",
    "OAuthProvider",
    "Platform",
    "PostType",
    "ReportFormat",
    "SentimentLabel",
    "UserRole",
    "AIAnalysis",
    "Agency",
    "ApiUsageLog",
    "Campaign",
    "CampaignInfluencer",
    "Comment",
    "Influencer",
    "OAuthState",
    "Plan",
    "Post",
    "Report",
    "SocialAccount",
    "User",
]
