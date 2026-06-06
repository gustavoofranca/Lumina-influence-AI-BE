"""Pipeline de mídia para análise multimodal (B9).

Interface plugável: baixa o vídeo de um post pra um arquivo temporário (que é
deletado após o uso) e expõe o caminho pro Gemini multimodal. O downloader real
usa HTTP; em testes é mockado (sem precisar de vídeos reais nem libs pesadas).

Extração de frames é opcional — com Gemini-nativo multimodal, mandamos o vídeo
inteiro e o modelo enxerga os frames internamente.
"""
from __future__ import annotations

import abc
import logging
import os
import tempfile
from dataclasses import dataclass

import requests

from src.utils.errors import LuminaError

logger = logging.getLogger(__name__)

TIMEOUT = 30
MAX_BYTES = 50 * 1024 * 1024  # 50MB — guarda contra vídeos gigantes


class VideoFetchError(LuminaError):
    status_code = 502
    code = "video_fetch_error"


@dataclass
class VideoAsset:
    path: str
    mime_type: str


class VideoFetcher(abc.ABC):
    """Contrato do downloader de vídeo (mockável)."""

    @abc.abstractmethod
    def fetch(self, video_url: str | None) -> VideoAsset: ...

    def cleanup(self, asset: VideoAsset | None) -> None:
        if asset and asset.path and os.path.exists(asset.path):
            try:
                os.remove(asset.path)
            except OSError as exc:
                logger.debug("Falha ao remover temp %s: %s", asset.path, exc)


class HttpVideoFetcher(VideoFetcher):
    """Baixa o vídeo via HTTP pra um arquivo temporário."""

    def fetch(self, video_url: str | None) -> VideoAsset:
        if not video_url:
            raise VideoFetchError("Post sem video_url — não há vídeo para analisar")
        try:
            resp = requests.get(video_url, stream=True, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise VideoFetchError("Falha ao baixar vídeo", details={"err": str(exc)[:200]}) from exc
        if resp.status_code != 200:
            raise VideoFetchError(
                "Download do vídeo retornou erro",
                details={"status": resp.status_code, "url": video_url[:120]},
            )

        mime = resp.headers.get("Content-Type", "video/mp4").split(";")[0]
        suffix = _suffix_for(mime, video_url)
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="lumina_vid_")
        written = 0
        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise VideoFetchError("Vídeo excede o tamanho máximo permitido")
                    fh.write(chunk)
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            raise
        return VideoAsset(path=path, mime_type=mime)


def _suffix_for(mime: str, url: str) -> str:
    mapping = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
    if mime in mapping:
        return mapping[mime]
    for ext in (".mp4", ".mov", ".webm"):
        if url.lower().endswith(ext):
            return ext
    return ".mp4"
