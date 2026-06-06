"""Blueprint /api/v1/reports — geração, listagem e download de relatórios PDF."""
from __future__ import annotations

from flask import Blueprint, g, send_file
from sqlalchemy import select

from src.extensions import db
from src.models import Report, UserRole
from src.schemas.report import ReportCreateIn, ReportOut
from src.services import report_service
from src.utils.auth_decorators import require_auth
from src.utils.authz import current_agency_id, get_scoped_or_404, require_role
from src.utils.errors import NotFoundError
from src.utils.pagination import paginate
from src.utils.responses import created, ok, paginated
from src.utils.validation import parse_json

bp = Blueprint("reports", __name__, url_prefix="/api/v1/reports")


def _dump(r: Report) -> dict:
    return ReportOut.model_validate(r).model_dump(mode="json")


@bp.get("")
@require_auth
def list_reports():
    stmt = (
        select(Report)
        .where(Report.agency_id == current_agency_id())
        .order_by(Report.generated_at.desc())
    )
    page = paginate(stmt)
    return paginated([_dump(r) for r in page.items], page)


@bp.get("/<report_id>")
@require_auth
def get_report(report_id):
    report = get_scoped_or_404(Report, report_id)
    return ok(_dump(report))


@bp.post("")
@require_auth
@require_role(UserRole.ADMIN, UserRole.MEMBER)
def create_report():
    payload = parse_json(ReportCreateIn)
    user = g.current_user
    report = report_service.generate_report(
        agency_id=current_agency_id(),
        generated_by_user_id=user.id,
        generated_by_name=user.name,
        campaign_id=payload.campaign_id,
        title=payload.title,
        period_start=payload.period_start,
        period_end=payload.period_end,
        sections=payload.sections,
    )
    return created(_dump(report))


@bp.get("/<report_id>/download")
@require_auth
def download_report(report_id):
    report = get_scoped_or_404(Report, report_id)
    path = report_service.report_pdf_path(report)
    if not path.exists():
        raise NotFoundError("Arquivo PDF não encontrado", code="pdf_missing")
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{report.title}.pdf",
    )
