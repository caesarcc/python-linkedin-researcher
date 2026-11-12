"""Fábrica de provedores de LLM baseada em configurações da aplicação."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from linkedin_researcher.llm.fallback_provider import FallbackOfflineProvider
from linkedin_researcher.llm.gemini_provider import GeminiProvider
from linkedin_researcher.llm.ollama_provider import OllamaProvider
from linkedin_researcher.llm.protocol import LLMProvider

if TYPE_CHECKING:
    from linkedin_researcher.config import AppConfig

logger = logging.getLogger(__name__)


def get_llm_provider(
    config: AppConfig | None = None,
    provider_override: str | None = None,
    client_override: Any | None = None,
) -> LLMProvider:
    """Retorna o provedor de LLM configurado (Ollama, Gemini ou Offline).

    Permite injeção de clientes mockados via client_override para testes unitários.
    """
    selected = (provider_override or (config.llm_provider if config else "ollama")).casefold().strip()

    if selected == "ollama":
        model = config.ollama_model if config else "qwen2.5:3b"
        base_url = config.ollama_base_url if config else "http://localhost:11434"
        timeout = config.ollama_timeout_sec if config else 60.0
        return OllamaProvider(
            model=model,
            base_url=base_url,
            timeout=timeout,
            client=client_override,
        )

    if selected == "gemini":
        model = config.gemini_model if config else "gemini-3.8-flash"
        api_key = config.gemini_api_key if config and hasattr(config, "gemini_api_key") else ""
        return GeminiProvider(
            model=model,
            api_key=api_key,
            client=client_override,
        )

    if selected in {"offline", "deterministic", "none", "local"}:
        return FallbackOfflineProvider()

    logger.warning(
        "Provedor de LLM desconhecido '%s'. Ativando fallback offline determinístico.",
        selected,
    )
    return FallbackOfflineProvider()

