"""Provedor determinístico offline para execução sem chamadas a modelos."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from linkedin_researcher.llm.protocol import LLMProvider

T = TypeVar("T", bound=BaseModel)


class FallbackOfflineProvider:
    """Provedor que não aciona nenhuma API nem consome recursos, permitindo fallback imediato."""

    @property
    def provider_name(self) -> str:
        return "offline"

    @property
    def model_name(self) -> str:
        return "deterministic-rules"

    def is_available(self) -> bool:
        return True

    def generate_structured(self, prompt: str, schema: type[T]) -> T | None:
        """Sempre retorna None para acionar a lógica heurística local determinística."""
        return None

