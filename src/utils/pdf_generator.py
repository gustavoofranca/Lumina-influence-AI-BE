"""Renderização de HTML → PDF (xhtml2pdf / pisa — puro Python, sem deps nativas).

Mantido como camada fina e plugável: se um dia trocarmos por WeasyPrint, só este
módulo muda.
"""
from __future__ import annotations

import io
import logging

from src.utils.errors import LuminaError

logger = logging.getLogger(__name__)


class PdfRenderError(LuminaError):
    status_code = 500
    code = "pdf_render_error"


def render_pdf(html: str) -> bytes:
    """Converte uma string HTML num PDF (bytes). Levanta PdfRenderError em falha."""
    from xhtml2pdf import pisa

    out = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    if result.err:
        raise PdfRenderError("Falha ao renderizar PDF", details={"errors": result.err})
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise PdfRenderError("Saída não é um PDF válido")
    return data
