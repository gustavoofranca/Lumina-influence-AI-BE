"""Renderização de HTML → PDF (xhtml2pdf / pisa — puro Python, sem deps nativas).

Mantido como camada fina e plugável: se um dia trocarmos por WeasyPrint, só este
módulo muda.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata

from src.utils.errors import LuminaError

logger = logging.getLogger(__name__)

# As fontes embarcadas pelo xhtml2pdf não cobrem emoji: cada um vira um quadrado
# preto no PDF. Embarcar uma fonte com essa cobertura pesaria em todo relatório
# gerado, então o caractere é removido — mas nunca em silêncio, para o problema
# não se esconder de quem gerou o documento.
_EMOJI_RE = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF" "\U0000FE00-\U0000FE0F" "\U00002B00-\U00002BFF"
    "]+"
)


def strip_unsupported_glyphs(html: str) -> str:
    """Remove emoji do HTML e registra em log o que foi retirado."""
    removidos = _EMOJI_RE.findall(html)
    if not removidos:
        return html
    nomes = []
    for trecho in removidos:
        for ch in trecho:
            nomes.append(unicodedata.name(ch, f"U+{ord(ch):04X}"))
    logger.warning(
        "PDF: %d caractere(s) sem glifo removido(s) do documento: %s",
        len(nomes), ", ".join(nomes[:8]),
    )
    return _EMOJI_RE.sub("", html)


class PdfRenderError(LuminaError):
    status_code = 500
    code = "pdf_render_error"


def render_pdf(html: str) -> bytes:
    """Converte uma string HTML num PDF (bytes). Levanta PdfRenderError em falha."""
    from xhtml2pdf import pisa

    out = io.BytesIO()
    result = pisa.CreatePDF(src=strip_unsupported_glyphs(html), dest=out, encoding="utf-8")
    if result.err:
        raise PdfRenderError("Falha ao renderizar PDF", details={"errors": result.err})
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise PdfRenderError("Saída não é um PDF válido")
    return data
