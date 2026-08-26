"""Geração de relatórios PDF a partir dos dados reais da campanha.

Reaproveita o `dashboard_service.campaign_benchmarking` (B5) pra os dados por
criador e compõe o contexto do template. Renderiza HTML→PDF e salva em
storage/reports/{report_id}.pdf.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app
from jinja2 import Environment, select_autoescape
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Campaign,
    Influencer,
    Post,
    Report,
    ReportFormat,
)
from src.services import dashboard_service
from src.services import metric_service as M
from src.services.report_template import REPORT_HTML
from src.utils.errors import NotFoundError, ValidationError
from src.utils.pdf_generator import render_pdf

logger = logging.getLogger(__name__)

SECTION_KEYS = ["kpis", "growth", "benchmark", "diagnostic", "recommendations"]


def build_report_query(agency_id: uuid.UUID):
    """SELECT de relatórios da agência, do mais recente para o mais antigo."""
    return (
        select(Report)
        .where(Report.agency_id == agency_id)
        .order_by(Report.generated_at.desc())
    )

_jinja = Environment(autoescape=select_autoescape(["html", "xml"]))
_template = _jinja.from_string(REPORT_HTML)


# ==========================================================================
# Formatação
# ==========================================================================
def _fmt_compact(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _fmt_brl(cents: int) -> str:
    return f"{(cents or 0) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ==========================================================================
# Contexto
# ==========================================================================
def build_report_context(
    *, campaign: Campaign, period_start: date, period_end: date, sections: list[str],
    title: str, generated_by: str,
) -> dict:
    bench = dashboard_service.campaign_benchmarking(
        campaign, period_start=period_start, period_end=period_end
    )
    rows = bench["influencers"]

    # Sumário executivo
    org_vals = [r["organic_pct"] for r in rows] or [0]
    sent_vals = [r["sentiment_index_pct"] or 0 for r in rows] or [0]
    total_reach = sum(r["total_reach"] for r in rows)
    posts_count = _count_campaign_posts(campaign.id, period_start, period_end)

    # Sem post no período não há o que medir. A distinção precisa viajar no
    # contexto: quem renderiza não tem como separar "medimos zero" de "não
    # medimos" olhando só para os números. Mesmo princípio da ADR-002.
    has_data = posts_count > 0

    summary = {
        "influencer_count": len(rows),
        "avg_organic_pct": round(sum(org_vals) / len(org_vals), 1),
        "avg_sentiment_pct": round(sum(sent_vals) / len(sent_vals), 1),
        "total_reach_fmt": _fmt_compact(total_reach),
        "posts_count": posts_count,
        "has_data": has_data,
    }

    # KPIs da campanha
    avg_eng = round(sum(r["engagement_rate"] for r in rows) / max(len(rows), 1), 2)
    # `depends_on_posts` diz quais cartões perdem o sentido num período sem
    # post. A contagem de criadores não é um deles: é fato do elenco da
    # campanha, não medição do período.
    kpis = [
        {"label": "Criadores", "value": str(len(rows)), "change": None,
         "depends_on_posts": False},
        {"label": "Alcance Total", "value": _fmt_compact(total_reach), "change": None,
         "depends_on_posts": True},
        {"label": "Engajamento Médio", "value": f"{avg_eng}%", "change": None,
         "depends_on_posts": True},
        {"label": "Sentimento Médio", "value": f"{summary['avg_sentiment_pct']}%",
         "change": None, "depends_on_posts": True},
    ]

    # Growth (orgânico vs pago por bucket) — só dos posts da campanha
    posts = _campaign_posts(campaign.id, period_start, period_end)
    growth_raw = M.growth_trajectory(posts, "90d")
    growth = [
        {
            "x": g["x"],
            # Cru para o gráfico da pré-visualização, formatado para o PDF.
            "organic": g["organic"],
            "paid": g["paid"],
            "organic_fmt": _fmt_compact(g["organic"]),
            "paid_fmt": _fmt_compact(g["paid"]),
        }
        for g in growth_raw
    ]

    # Benchmark
    benchmark = [
        {
            "display_name": r["display_name"],
            "total_reach_fmt": _fmt_compact(r["total_reach"]),
            "organic_pct": r["organic_pct"],
            "engagement_rate": r["engagement_rate"],
            "sentiment_index_pct": r["sentiment_index_pct"] or 0,
            "ai_score": r["ai_score"],
        }
        for r in rows
    ]

    # Diagnostic (top 2 por score IA)
    diagnostic = []
    for r in sorted(rows, key=lambda x: x["ai_score"], reverse=True)[:2]:
        inf = db.session.get(Influencer, uuid.UUID(r["influencer_id"]))
        ai = M.ai_aggregates(M.fetch_influencer_analyses(inf.id))
        coh = ai["brand_coherence"] or 0
        bot = ai["bot_probability"] or 0
        note = (
            f"Análise indica alinhamento {'forte' if coh > 85 else 'parcial'} com a marca, "
            f"sentimento {'majoritariamente positivo' if (ai['sentiment_index_pct'] or 0) >= 80 else 'misto'} "
            f"e probabilidade de bot {'baixa' if bot < 5 else 'a monitorar'}."
        )
        diagnostic.append({
            "display_name": inf.display_name, "niche": inf.niche or "—",
            "brand_coherence": round(coh, 1), "bot_probability": round(bot, 1), "note": note,
        })

    # Recommendations — agrega das análises recentes dos criadores da campanha
    recommendations = _gather_recommendations(rows)

    return {
        "report_title": title,
        "campaign": {
            "brand_name": campaign.brand_name,
            "title": campaign.title,
        },
        "period_start": period_start.strftime("%d/%m/%Y"),
        "period_end": period_end.strftime("%d/%m/%Y"),
        "budget_brl": _fmt_brl(campaign.budget_brl_cents),
        "generated_by": generated_by,
        "generated_at": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        "summary": summary,
        "sections": [s for s in sections if s in SECTION_KEYS],
        "kpis": kpis,
        "growth": growth,
        "benchmark": benchmark,
        "diagnostic": diagnostic,
        "recommendations": recommendations,
    }


def _posts_in_period(campaign_id: uuid.UUID, period_start: date, period_end: date):
    """Posts da campanha dentro do intervalo declarado na capa do relatório."""
    return (
        select(Post)
        .where(Post.campaign_id == campaign_id)
        .where(func.date(Post.posted_at) >= period_start)
        .where(func.date(Post.posted_at) <= period_end)
    )


def _campaign_posts(campaign_id: uuid.UUID, period_start: date, period_end: date) -> list[Post]:
    return list(db.session.scalars(_posts_in_period(campaign_id, period_start, period_end)).all())


def _count_campaign_posts(campaign_id: uuid.UUID, period_start: date, period_end: date) -> int:
    subq = _posts_in_period(campaign_id, period_start, period_end).subquery()
    return int(db.session.scalar(select(func.count()).select_from(subq)) or 0)


def _gather_recommendations(rows: list[dict]) -> list[dict]:
    recs: list[dict] = []
    seen = set()
    for r in rows:
        analyses = M.fetch_influencer_analyses(uuid.UUID(r["influencer_id"]))
        for a in analyses:
            for item in (a.recommendations or []):
                if isinstance(item, dict):
                    title = item.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        recs.append({"title": title, "description": item.get("description", "")})
            if len(recs) >= 5:
                break
        if len(recs) >= 5:
            break
    if not recs:
        recs = [{"title": "Manter monitoramento contínuo",
                 "description": "Sem recomendações de IA registradas para o período. Rode análises nos posts da campanha."}]
    return recs[:5]


# ==========================================================================
# Geração
# ==========================================================================
def _storage_dir() -> Path:
    base = Path(current_app.root_path).parent / "storage" / "reports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def generate_report(
    *, agency_id: uuid.UUID, generated_by_user_id: uuid.UUID | None, generated_by_name: str,
    campaign_id: uuid.UUID, title: str, period_start: date, period_end: date, sections: list[str],
) -> Report:
    campaign = db.session.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.agency_id == agency_id)
    )
    if campaign is None:
        raise NotFoundError("Campaign não encontrada")
    if period_end < period_start:
        raise ValidationError("period_end não pode ser anterior a period_start")

    report = Report(
        agency_id=agency_id,
        campaign_id=campaign_id,
        generated_by_user_id=generated_by_user_id,
        title=title,
        period_start=period_start,
        period_end=period_end,
        format=ReportFormat.PDF,
        sections={"included": [s for s in sections if s in SECTION_KEYS]},
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(report)
    db.session.flush()  # garante report.id

    context = build_report_context(
        campaign=campaign, period_start=period_start, period_end=period_end,
        sections=sections, title=title, generated_by=generated_by_name,
    )
    html = _template.render(**context)
    pdf_bytes = render_pdf(html)

    path = _storage_dir() / f"{report.id}.pdf"
    path.write_bytes(pdf_bytes)
    report.pdf_url = f"/api/v1/reports/{report.id}/download"
    db.session.commit()

    logger.info("Relatório gerado: id=%s campanha=%s bytes=%d", report.id, campaign_id, len(pdf_bytes))
    return report


def report_pdf_path(report: Report) -> Path:
    return _storage_dir() / f"{report.id}.pdf"


def ensure_pdf(report: Report) -> Path:
    """Garante que o PDF existe no disco; gera sob demanda se faltar.

    Relatórios seedados (B2) têm metadados mas não o arquivo — esta função
    materializa o PDF na primeira vez que é baixado.
    """
    path = report_pdf_path(report)
    if path.exists():
        return path
    campaign = db.session.get(Campaign, report.campaign_id) if report.campaign_id else None
    if campaign is None:
        raise NotFoundError("Campanha do relatório não existe mais")
    sections = (report.sections or {}).get("included") or SECTION_KEYS
    context = build_report_context(
        campaign=campaign, period_start=report.period_start, period_end=report.period_end,
        sections=sections, title=report.title, generated_by="Equipe Lumina",
    )
    html = _template.render(**context)
    path.write_bytes(render_pdf(html))
    logger.info("PDF gerado sob demanda: report=%s", report.id)
    return path
