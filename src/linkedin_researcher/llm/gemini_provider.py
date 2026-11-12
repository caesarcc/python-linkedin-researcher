"""Provedor de inferência em nuvem via Gemini API (google-genai)."""

from __future__ import annotations

import logging
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from linkedin_researcher.llm.protocol import LLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    """Implementa integração com modelos Google Gemini utilizando o SDK google-genai."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash",
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model.strip() or "gemini-3.8-flash"
        self._api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self._client = client

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def is_available(self) -> bool:
        """Verifica se há chave de API ou cliente instanciado."""
        return bool(self._api_key or self._client is not None)

    def generate_structured(self, prompt: str, schema: type[T]) -> T | None:
        """Gera resposta formatada via structured outputs da API Gemini e valida com Pydantic."""
        if not self.is_available():
            logger.debug("GeminiProvider chamado sem API_KEY configurada.")
            return None

        try:
            client = self._get_client()
            interaction = client.interactions.create(
                model=self._model,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema.model_json_schema(),
                },
            )
            if interaction and getattr(interaction, "output_text", None):
                return schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            logger.warning(
                "Falha ao chamar Gemini API (%s: %s). Usando fallback determinístico.",
                self._model,
                exc,
            )

        return None
