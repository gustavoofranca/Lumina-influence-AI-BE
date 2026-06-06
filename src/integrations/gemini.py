"""Wrapper fino sobre o SDK google-genai.

Responsabilidade: transporte (chamar o modelo, devolver texto + uso de tokens) e
tradução de erros do SDK pra exceções LuminaError. O parsing de domínio (JSON →
campos de análise) fica no `ai_analysis_service`, não aqui.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import current_app

from src.utils.errors import LuminaError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiError(LuminaError):
    status_code = 502
    code = "gemini_error"


class GeminiQuotaError(GeminiError):
    status_code = 429
    code = "gemini_quota_exceeded"


class GeminiNotConfiguredError(GeminiError):
    status_code = 503
    code = "gemini_not_configured"


@dataclass
class GeminiResult:
    text: str
    total_tokens: int
    model: str


class GeminiClient:
    """Cliente do Gemini. Instancia o SDK só quando há API key configurada."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or current_app.config.get("GEMINI_API_KEY")
        self._model = model or current_app.config.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._timeout = current_app.config.get("GEMINI_TIMEOUT_SECONDS", 30)
        if not self._api_key:
            raise GeminiNotConfiguredError(
                "GEMINI_API_KEY não configurada",
                details={"missing": ["GEMINI_API_KEY"]},
            )
        # Import tardio: só carrega o SDK quando realmente vamos usar.
        from google import genai

        self._client = genai.Client(api_key=self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def generate_json(self, prompt: str) -> GeminiResult:
        """Pede ao modelo uma resposta em JSON. Devolve texto bruto + tokens usados."""
        from google.genai import types
        from google.genai import errors as genai_errors

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
            http_options=types.HttpOptions(timeout=self._timeout * 1000),
        )
        try:
            resp = self._client.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        except genai_errors.ClientError as exc:
            # 429 = quota; demais 4xx = erro de request.
            status = getattr(exc, "code", None)
            if status == 429:
                raise GeminiQuotaError(
                    "Cota do Gemini excedida", details={"status": status}
                ) from exc
            raise GeminiError(
                "Gemini rejeitou a requisição", details={"status": status, "msg": str(exc)[:300]}
            ) from exc
        except genai_errors.ServerError as exc:
            raise GeminiError(
                "Gemini indisponível (erro 5xx)", details={"msg": str(exc)[:300]}
            ) from exc
        except Exception as exc:  # timeout, rede, etc.
            raise GeminiError(
                "Falha ao chamar Gemini", details={"msg": str(exc)[:300]}
            ) from exc

        text = (resp.text or "").strip()
        if not text:
            raise GeminiError("Gemini retornou resposta vazia")

        total_tokens = 0
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_token_count", 0) or 0

        return GeminiResult(text=text, total_tokens=total_tokens, model=self._model)

    def generate_json_with_video(
        self, prompt: str, video_path: str, mime_type: str = "video/mp4"
    ) -> GeminiResult:
        """Análise multimodal: sobe o vídeo (Files API), pede JSON e limpa o arquivo remoto.

        Gemini processa o vídeo internamente (transcrição + visão), sem Whisper.
        """
        import time

        from google.genai import errors as genai_errors
        from google.genai import types

        uploaded = None
        try:
            uploaded = self._client.files.upload(file=video_path)
            # Vídeos passam por PROCESSING antes de ficarem ACTIVE.
            for _ in range(self._timeout):
                state = getattr(uploaded, "state", None)
                state_name = getattr(state, "name", state)
                if state_name == "ACTIVE":
                    break
                if state_name == "FAILED":
                    raise GeminiError("Processamento do vídeo no Gemini falhou")
                time.sleep(1)
                uploaded = self._client.files.get(name=uploaded.name)

            config = types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.4
            )
            resp = self._client.models.generate_content(
                model=self._model, contents=[uploaded, prompt], config=config
            )
        except genai_errors.ClientError as exc:
            status = getattr(exc, "code", None)
            if status == 429:
                raise GeminiQuotaError("Cota do Gemini excedida", details={"status": status}) from exc
            raise GeminiError("Gemini rejeitou a requisição multimodal",
                              details={"status": status, "msg": str(exc)[:300]}) from exc
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError("Falha na análise multimodal", details={"msg": str(exc)[:300]}) from exc
        finally:
            if uploaded is not None:
                try:
                    self._client.files.delete(name=uploaded.name)
                except Exception:
                    pass

        text = (resp.text or "").strip()
        if not text:
            raise GeminiError("Gemini retornou resposta multimodal vazia")
        total_tokens = 0
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_token_count", 0) or 0
        return GeminiResult(text=text, total_tokens=total_tokens, model=self._model)
