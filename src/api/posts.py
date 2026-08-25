"""Blueprint /api/v1/posts — detalhe, histórico de análises e disparo de análise IA.

Escopo: post pertence à agência via social_account -> influencer -> agency.
"""
from __future__ import annotations

from flask import Blueprint, current_app, request

from src.models import Post, UserRole
from src.schemas.analysis import AIAnalysisOut, PostOut
from src.services import post_service
from src.services.ai_analysis_service import analyze_post, analyze_post_multimodal
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, require_role
from src.utils.rate_limit import rate_limit
from src.utils.responses import created, ok

bp = Blueprint("posts", __name__, url_prefix="/api/v1/posts")


def _load_scoped_post(post_id) -> Post:
    return post_service.load_scoped_post(post_id, current_agency_id())


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
    analyses = post_service.list_analyses(post.id)
    return ok([AIAnalysisOut.model_validate(a).model_dump(mode="json") for a in analyses])


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


@bp.post("/<post_id>/analyze")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
@rate_limit("RATE_LIMIT_ANALYZE")
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
