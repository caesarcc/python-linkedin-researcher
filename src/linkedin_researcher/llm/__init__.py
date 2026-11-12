"""Módulo de provedores desacoplados de LLM para inferência local e em nuvem."""

from linkedin_researcher.llm.factory import get_llm_provider
from linkedin_researcher.llm.fallback_provider import FallbackOfflineProvider
from linkedin_researcher.llm.gemini_provider import GeminiProvider
from linkedin_researcher.llm.ollama_provider import OllamaProvider
from linkedin_researcher.llm.protocol import LLMProvider

__all__ = [
    "LLMProvider",
    "OllamaProvider",
    "GeminiProvider",
    "FallbackOfflineProvider",
    "get_llm_provider",
]

