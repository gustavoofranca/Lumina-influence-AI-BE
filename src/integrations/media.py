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

# Tipos que nunca são vídeo. A lista é de exclusão, e não de permissão, porque
# CDN de vídeo costuma servir `application/octet-stream` — recusar o que não
# está numa lista de permitidos rejeitaria download legítimo.
#
# O caso concreto é uma URL de *página* chegando onde se espera arquivo: o
# servidor devolve 200 com HTML, e sem esta guarda o HTML era gravado com
# sufixo `.mp4` e enviado ao analisador como se fosse vídeo.
MIMES_QUE_NAO_SAO_VIDEO = ("text/", "application/json", "application/xml", "application/xhtml")


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

        mime = resp.headers.get("Content-Type", "video/mp4").split(";")[0].strip()
        if mime.startswith(MIMES_QUE_NAO_SAO_VIDEO):
            raise VideoFetchError(
                "A URL não devolveu vídeo",
                details={"mime": mime, "url": video_url[:120]},
            )
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


class LocalFileFetcher(VideoFetcher):
    """Serve um vídeo que já está em disco, em vez de baixá-lo.

    Existe para o upload pela interface: o arquivo chega pelo formulário e é
    gravado antes da análise, então não há o que baixar. Implementar o mesmo
    contrato — em vez de abrir uma exceção dentro de `analyze_post_multimodal` —
    mantém um caminho de análise só: quem envia ao modelo, valida o JSON e
    persiste continua sendo a função de sempre.

    `cleanup` é deliberadamente inerte. O arquivo é do produto, não temporário:
    apagá-lo ao fim da análise destruiria a mídia do post que acabou de ser
    criado. Quem baixa da rede continua limpando o temporário, porque ali o
    arquivo só existia para a chamada.
    """

    def __init__(self, path: str, mime_type: str = "video/mp4") -> None:
        self._path = path
        self._mime = mime_type

    def fetch(self, video_url: str | None) -> VideoAsset:
        # `video_url` é ignorado de propósito: o contrato o recebe porque o
        # fetcher de rede precisa dele, e mudar a assinatura para este caso
        # obrigaria o chamador a saber qual dos dois está usando.
        if not os.path.exists(self._path):
            raise VideoFetchError(
                "Arquivo de vídeo não encontrado no armazenamento",
                details={"path": os.path.basename(self._path)},
            )
        tamanho = os.path.getsize(self._path)
        if tamanho > MAX_BYTES:
            raise VideoFetchError(
                "Vídeo excede o tamanho máximo permitido",
                details={"bytes": tamanho, "max": MAX_BYTES},
            )
        return VideoAsset(path=self._path, mime_type=self._mime)

    def cleanup(self, asset: VideoAsset | None) -> None:
        return None


def _suffix_for(mime: str, url: str) -> str:
    mapping = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
    if mime in mapping:
        return mapping[mime]
    for ext in (".mp4", ".mov", ".webm"):
        if url.lower().endswith(ext):
            return ext
    return ".mp4"
