"""Enums do domínio. Mapeiam pra ENUM nativo no Postgres e VARCHAR+CHECK em SQLite."""
from __future__ import annotations

import enum


class OAuthProvider(str, enum.Enum):
    """Provedor que emitiu o `state` cujo uso único registramos.

    Nasceu servindo só ao login (Google e Microsoft). As redes sociais entraram
    depois porque o callback de integração usa a mesma tabela `oauth_states`
    para gastar o `jti` do state, e sem valor no enum o consumo do nonce falhava
    fechado — Instagram e TikTok ficavam inalcançáveis mesmo com credencial
    configurada. `meta` em vez de `instagram` por fidelidade: o token que volta
    do consentimento é de usuário do Facebook, não do perfil do Instagram.
    """

    GOOGLE = "google"
    MICROSOFT = "microsoft"
    META = "meta"
    TIKTOK = "tiktok"


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


class RecommendationDecisionKind(str, enum.Enum):
    """O que a agência fez com uma recomendação da IA."""

    ACCEPTED = "accepted"
    IGNORED = "ignored"


class SentimentLabel(str, enum.Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class ReportFormat(str, enum.Enum):
    PDF = "pdf"
    JSON = "json"
