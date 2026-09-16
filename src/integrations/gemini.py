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


class GeminiUnavailableError(GeminiError):
    """O modelo está sobrecarregado agora — condição temporária, do lado do Google.

    Existe separada de `GeminiError` porque a ação de quem recebe é outra: não
    há nada a corrigir na requisição, no arquivo nem na credencial; é esperar e
    repetir. Enquanto as duas compartilhavam a mesma mensagem genérica, um 503
    do Google mandava quem operava procurar defeito na própria configuração.
    """

    status_code = 503
    code = "gemini_unavailable"


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
        # Reserva para sobrecarga: o 503 "high demand" é por modelo, não geral.
        # Vazio desliga a reserva. Só vale para 5xx — cota (429) e requisição
        # inválida (4xx) falhariam igual em qualquer modelo.
        self._reserva = current_app.config.get("GEMINI_FALLBACK_MODEL") or None
        self._tentativas = max(1, int(current_app.config.get("GEMINI_RETRIES", 2)))
        self._espera = float(current_app.config.get("GEMINI_RETRY_BACKOFF_SECONDS", 3))
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

    def _gerar(self, contents, config):
        """Chama o modelo com nova tentativa em 5xx e, esgotadas, o modelo de reserva.

        Devolve `(resposta, modelo_que_respondeu)`. O nome do modelo volta junto
        porque ele vai para `model_version` da análise: registrar o principal
        quando quem respondeu foi a reserva seria afirmar procedência falsa
        sobre o próprio resultado da IA.

        Em 503 persistente relança o último `ServerError`, e quem chamou o
        converte em `GeminiUnavailableError` como antes — a tela continua
        dizendo que é sobrecarga do Google, só que depois de insistir.
        """
        import time as _time

        from google.genai import errors as genai_errors

        modelos = [self._model] + ([self._reserva] if self._reserva and self._reserva != self._model else [])
        ultimo = None
        for modelo in modelos:
            for tentativa in range(self._tentativas):
                try:
                    resp = self._client.models.generate_content(
                        model=modelo, contents=contents, config=config
                    )
                    if modelo != self._model:
                        logger.warning(
                            "Gemini %s sobrecarregado; análise feita pelo modelo de reserva %s",
                            self._model, modelo,
                        )
                    return resp, modelo
                except genai_errors.ServerError as exc:
                    ultimo = exc
                    logger.info(
                        "Gemini %s respondeu 5xx (tentativa %d de %d)",
                        modelo, tentativa + 1, self._tentativas,
                    )
                    if tentativa + 1 < self._tentativas and self._espera > 0:
                        _time.sleep(self._espera * (tentativa + 1))
        raise ultimo

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
            resp, modelo_usado = self._gerar(prompt, config)
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
            raise GeminiUnavailableError(
                "O modelo de IA está sobrecarregado no momento. "
                "É temporário, do lado do Google — tente novamente em alguns minutos.",
                details={"msg": str(exc)[:300]},
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

        return GeminiResult(text=text, total_tokens=total_tokens, model=modelo_usado)

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
            # O arquivo sobe uma vez só; a nova tentativa repete apenas a geração.
            resp, modelo_usado = self._gerar([uploaded, prompt], config)
        except genai_errors.ClientError as exc:
            status = getattr(exc, "code", None)
            if status == 429:
                raise GeminiQuotaError("Cota do Gemini excedida", details={"status": status}) from exc
            raise GeminiError("Gemini rejeitou a requisição multimodal",
                              details={"status": status, "msg": str(exc)[:300]}) from exc
        except genai_errors.ServerError as exc:
            # O caminho de texto já separava 5xx; o de vídeo caía no `except
            # Exception` abaixo e virava "Falha na análise multimodal", que
            # mandava quem operava caçar defeito de configuração num problema
            # que era de capacidade do Google.
            raise GeminiUnavailableError(
                "O modelo de IA está sobrecarregado no momento. "
                "É temporário, do lado do Google — tente novamente em alguns minutos.",
                details={"msg": str(exc)[:300]},
            ) from exc
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError("Falha na análise multimodal", details={"msg": str(exc)[:300]}) from exc
        finally:
            if uploaded is not None:
                try:
                    self._client.files.delete(name=uploaded.name)
                except Exception as exc:
                    logger.warning(
                        "Falha ao remover arquivo enviado ao Gemini: %s (%s)",
                        uploaded.name,
                        str(exc)[:200],
                    )

        text = (resp.text or "").strip()
        if not text:
            raise GeminiError("Gemini retornou resposta multimodal vazia")
        total_tokens = 0
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_token_count", 0) or 0
        return GeminiResult(text=text, total_tokens=total_tokens, model=modelo_usado)
