"""Protocolo e tipos base para provedores desacoplados de LLM."""

from __future__ import annotations

from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Interface abstrata para provedores de modelos de linguagem (Ollama, Gemini, Offline)."""

    @property
    def provider_name(self) -> str:
        """Nome do provedor ('ollama', 'gemini', 'offline')."""
        ...

    @property
    def model_name(self) -> str:
        """Identificador do modelo em execução (ex: 'qwen2.5:3b', 'gemini-3.8-flash')."""
        ...

    def is_available(self) -> bool:
        """Verifica se o provedor está acessível e pronto para receber inferências."""
        ...

    def generate_structured(self, prompt: str, schema: type[T]) -> T | None:
        """Executa a inferência e retorna uma instância tipada e validada do schema Pydantic.

        Retorna None se houver falha de rede, timeout, ou erro de validação sintática.
        """
        ...
