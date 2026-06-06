"""Blueprint /api/v1/posts — detalhe, histórico de análises e disparo de análise IA.

Escopo: post pertence à agência via social_account -> influencer -> agency.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, current_app, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.extensions import db
from src.models import AIAnalysis, Influencer, Post, SocialAccount, UserRole
from src.schemas.analysis import AIAnalysisOut, PostOut
from src.services.ai_analysis_service import analyze_post, analyze_post_multimodal
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, require_role
from src.utils.errors import NotFoundError
from src.utils.responses import created, ok

bp = Blueprint("posts", __name__, url_prefix="/api/v1/posts")


def _load_scoped_post(post_id) -> Post:
    try:
        pid = uuid.UUID(str(post_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("Post não encontrado") from exc
    post = db.session.scalar(
        select(Post)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .join(Influencer, SocialAccount.influencer_id == Influencer.id)
        .where(Post.id == pid, Influencer.agency_id == current_agency_id())
        .options(selectinload(Post.social_account).selectinload(SocialAccount.influencer))
    )
    if post is None:
        raise NotFoundError("Post não encontrado")
    return post


@bp.get("/<post_id>")
@require_auth
def get_post(post_id):
    post = _load_scoped_post(post_id)
    return ok(PostOut.model_validate(post).model_dump(mode="json"))


@bp.get("/<post_id>/analyses")
@require_auth
def list_post_analyses(post_id):
    """Histórico de análises do post (mais recente primeiro)."""
    post = _load_scoped_post(post_id)
    analyses = db.session.scalars(
        select(AIAnalysis)
        .where(AIAnalysis.post_id == post.id)
        .order_by(AIAnalysis.analyzed_at.desc())
    ).all()
    return ok([AIAnalysisOut.model_validate(a).model_dump(mode="json") for a in analyses])


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


@bp.post("/<post_id>/analyze")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def analyze(post_id):
    """Dispara análise síncrona via Gemini e persiste uma nova AIAnalysis.

    `?multimodal=true` faz a análise considerar o vídeo (transcrição + visão).
    """
    post = _load_scoped_post(post_id)
    max_comments = current_app.config.get("GEMINI_MAX_COMMENTS", 30)
    if _truthy(request.args.get("multimodal")):
        analysis = analyze_post_multimodal(
            post, agency_id=current_agency_id(), max_comments=max_comments
        )
    else:
        analysis = analyze_post(post, agency_id=current_agency_id(), max_comments=max_comments)
    return created(AIAnalysisOut.model_validate(analysis).model_dump(mode="json"))
