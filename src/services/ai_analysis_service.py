"""Orquestra a análise de IA de um post via Gemini.

Fluxo (B6):
1. Busca post + amostra de comentários.
2. Monta prompt estruturado pedindo JSON com regras claras.
3. Chama o Gemini (client injetável p/ testes).
4. Parseia a resposta com tolerância a falhas (fences markdown, campos faltando).
5. Persiste uma nova AIAnalysis (versionada — sempre cria nova).
6. Loga uso em ApiUsageLog.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from src.extensions import db
from src.integrations.gemini import GeminiClient, GeminiError
from src.models import (
    AIAnalysis,
    ApiUsageLog,
    Comment,
    Post,
    SentimentLabel,
)
from src.utils.errors import LuminaError

logger = logging.getLogger(__name__)

ANALYZE_ENDPOINT = "POST /api/v1/posts/:id/analyze"
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class AnalysisParseError(LuminaError):
    status_code = 502
    code = "analysis_parse_error"


# ==========================================================================
# Prompt
# ==========================================================================
PROMPT_TEMPLATE = """\
Você é um analista sênior de marketing de influência. Analise o post abaixo e a \
amostra de comentários do público. Responda APENAS com um objeto JSON válido, sem \
texto fora do JSON, seguindo EXATAMENTE este schema:

{{
  "sentiment_score": <float entre -1 e 1>,
  "sentiment_label": "positive" | "neutral" | "negative",
  "sentiment_breakdown": {{
    "technical_enthusiasm": <int 0-100>,
    "purchase_intent": <int 0-100>,
    "value_skepticism": <int 0-100>,
    "neutral": <int 0-100>
  }},
  "script_score": <float 0-10>,
  "brand_coherence_score": <float 0-100>,
  "bot_probability": <float 0-100>,
  "key_phrases": [<string>, ...],
  "recommendations": [
    {{"priority": "high"|"medium"|"low", "title": <string>, "description": <string>}}
  ]
}}

Regras:
- sentiment_breakdown deve somar aproximadamente 100.
- key_phrases: 4 a 8 termos relevantes extraídos dos comentários.
- recommendations: 2 a 3 itens acionáveis para a agência.
- Seja objetivo e baseie-se nos dados fornecidos.

=== DADOS DO POST ===
Nicho do influenciador: {niche}
Plataforma: {platform}
Tipo de post: {post_type}
Legenda: {caption}
Métricas: alcance_total={reach_total}, likes={likes}, comentários={comments_count}, \
compartilhamentos={shares}, salvamentos={saves}

=== AMOSTRA DE COMENTÁRIOS ({n_comments}) ===
{comments_block}
"""


def _build_prompt(post: Post, comments: list[Comment]) -> str:
    sa = post.social_account
    influencer_niche = sa.influencer.niche if sa and sa.influencer else "desconhecido"
    comments_block = "\n".join(f"- {c.content}" for c in comments) or "(sem comentários)"
    return PROMPT_TEMPLATE.format(
        niche=influencer_niche,
        platform=sa.platform.value if sa else "?",
        post_type=post.post_type.value,
        caption=(post.caption or "")[:500],
        reach_total=post.reach_total,
        likes=post.likes,
        comments_count=post.comments_count,
        shares=post.shares,
        saves=post.saves,
        n_comments=len(comments),
        comments_block=comments_block,
    )


# ==========================================================================
# Parsing tolerante
# ==========================================================================
def _clamp(value, low, high, default=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, v))


def parse_analysis_payload(text: str) -> dict:
    """Extrai e valida o JSON da resposta do Gemini. Tolera fences markdown."""
    cleaned = _FENCE_RE.sub("", text).strip()
    # Se ainda houver lixo antes/depois, tenta isolar o primeiro objeto {...}.
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        raw = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AnalysisParseError(
            "Resposta do Gemini não é JSON válido", details={"snippet": text[:200]}
        ) from exc
    if not isinstance(raw, dict):
        raise AnalysisParseError("JSON do Gemini não é um objeto")

    sentiment_score = _clamp(raw.get("sentiment_score"), -1, 1, default=0.0)

    label_raw = str(raw.get("sentiment_label", "")).lower()
    if label_raw not in {"positive", "neutral", "negative"}:
        # Deriva do score se vier inválido.
        label_raw = (
            "positive" if sentiment_score > 0.2
            else "negative" if sentiment_score < -0.2
            else "neutral"
        )

    breakdown = raw.get("sentiment_breakdown")
    if not isinstance(breakdown, dict):
        breakdown = None

    key_phrases = raw.get("key_phrases")
    if not isinstance(key_phrases, list):
        key_phrases = []
    key_phrases = [str(k) for k in key_phrases][:12]

    recommendations = raw.get("recommendations")
    if not isinstance(recommendations, list):
        recommendations = []

    return {
        "sentiment_score": sentiment_score,
        "sentiment_label": SentimentLabel(label_raw),
        "sentiment_breakdown": breakdown,
        "script_score": _clamp(raw.get("script_score"), 0, 10),
        "brand_coherence_score": _clamp(raw.get("brand_coherence_score"), 0, 100),
        "bot_probability": _clamp(raw.get("bot_probability"), 0, 100),
        "key_phrases": key_phrases,
        "recommendations": recommendations,
        "raw": raw,
    }


# ==========================================================================
# Orquestração
# ==========================================================================
def analyze_post(
    post: Post,
    *,
    agency_id: uuid.UUID,
    client: GeminiClient | None = None,
    max_comments: int = 30,
) -> AIAnalysis:
    """Roda a análise de um post e persiste uma nova AIAnalysis. `client` injetável p/ testes."""
    comments = list(
        db.session.scalars(
            select(Comment)
            .where(Comment.post_id == post.id)
            .order_by(Comment.like_count.desc())
            .limit(max_comments)
        ).all()
    )

    gemini = client or GeminiClient()
    prompt = _build_prompt(post, comments)

    result = gemini.generate_json(prompt)
    parsed = parse_analysis_payload(result.text)

    analysis = AIAnalysis(
        post_id=post.id,
        analyzed_at=datetime.now(timezone.utc),
        model_version=result.model,
        sentiment_score=parsed["sentiment_score"],
        sentiment_label=parsed["sentiment_label"],
        script_score=parsed["script_score"],
        brand_coherence_score=parsed["brand_coherence_score"],
        bot_probability=parsed["bot_probability"],
        transcript_text=None,  # multimodal é B9
        key_phrases=parsed["key_phrases"],
        recommendations=parsed["recommendations"],
        sentiment_breakdown=parsed["sentiment_breakdown"],
        raw_response=parsed["raw"],
    )
    db.session.add(analysis)

    usage = ApiUsageLog(
        agency_id=agency_id,
        endpoint=ANALYZE_ENDPOINT,
        tokens_used=result.total_tokens,
        called_at=datetime.now(timezone.utc),
    )
    db.session.add(usage)
    db.session.commit()

    logger.info(
        "Análise IA persistida: post=%s model=%s tokens=%s",
        post.id, result.model, result.total_tokens,
    )
    return analysis
