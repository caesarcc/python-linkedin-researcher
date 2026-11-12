"""Testes unitários para o módulo desacoplado de LLM (Ollama, Gemini e Fallback)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from linkedin_researcher.analysis.job_matching import JobMatchingResult, evaluate_job_match
from linkedin_researcher.config import AppConfig, load_config
from linkedin_researcher.llm import (
    FallbackOfflineProvider,
    GeminiProvider,
    OllamaProvider,
    get_llm_provider,
)
from linkedin_researcher.messaging.message_generator import generate_message_draft
from linkedin_researcher.models import CandidateProfile, Job, MatchLevel, SuggestedMessage


class SampleSchema(BaseModel):
    message: str
    score: int


def test_factory_returns_expected_providers() -> None:
    """Verifica se o factory instancia o provedor correto para cada configuração."""
    ollama_prov = get_llm_provider(provider_override="ollama")
    assert isinstance(ollama_prov, OllamaProvider)
    assert ollama_prov.provider_name == "ollama"

    gemini_prov = get_llm_provider(provider_override="gemini")
    assert isinstance(gemini_prov, GeminiProvider)
    assert gemini_prov.provider_name == "gemini"

    offline_prov = get_llm_provider(provider_override="offline")
    assert isinstance(offline_prov, FallbackOfflineProvider)
    assert offline_prov.provider_name == "offline"

    unknown_prov = get_llm_provider(provider_override="xyz-nao-existe")
    assert isinstance(unknown_prov, FallbackOfflineProvider)


def test_ollama_provider_is_available_success() -> None:
    """Verifica detecção de disponibilidade quando o modelo está na lista do Ollama."""
    mock_client = MagicMock()
    mock_model_obj = MagicMock()
    mock_model_obj.model = "qwen2.5:3b"
    mock_client.list.return_value = MagicMock(models=[mock_model_obj])

    provider = OllamaProvider(model="qwen2.5:3b", client=mock_client)
    assert provider.is_available() is True


def test_ollama_provider_is_available_missing_model() -> None:
    """Verifica detecção quando o modelo configurado não foi baixado no Ollama."""
    mock_client = MagicMock()
    mock_model_obj = MagicMock()
    mock_model_obj.model = "mistral:7b"
    mock_client.list.return_value = MagicMock(models=[mock_model_obj])

    provider = OllamaProvider(model="qwen2.5:3b", client=mock_client)
    assert provider.is_available() is False


def test_ollama_provider_generate_structured_success() -> None:
    """Valida geração estruturada com resposta JSON do Ollama parseada via Pydantic."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = '{"message": "Olá mundo", "score": 95}'
    mock_client.chat.return_value = mock_response

    provider = OllamaProvider(model="qwen2.5:3b", client=mock_client)
    result = provider.generate_structured("Teste prompt", SampleSchema)

    assert result is not None
    assert isinstance(result, SampleSchema)
    assert result.message == "Olá mundo"
    assert result.score == 95


def test_ollama_provider_generate_structured_handles_exception() -> None:
    """Garante que falhas de conexão no Ollama retornem None sem crashar a aplicação."""
    mock_client = MagicMock()
    mock_client.chat.side_effect = ConnectionError("Servidor offline")

    provider = OllamaProvider(model="qwen2.5:3b", client=mock_client)
    result = provider.generate_structured("Teste prompt", SampleSchema)
    assert result is None


def test_gemini_provider_generate_structured_success() -> None:
    """Valida geração estruturada do GeminiProvider utilizando mock do client interaction."""
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = '{"message": "Gemini resposta", "score": 88}'
    mock_client.interactions.create.return_value = mock_interaction

    provider = GeminiProvider(model="gemini-3.8-flash", client=mock_client)
    assert provider.is_available() is True
    result = provider.generate_structured("Prompt", SampleSchema)

    assert result is not None
    assert result.message == "Gemini resposta"
    assert result.score == 88


def test_evaluate_job_match_with_mock_ollama_provider() -> None:
    """Testa integração fim a fim do evaluate_job_match com OllamaProvider mockado."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = (
        '{"match_score": 85.0, "match_level": "Alta aderência", '
        '"strengths": ["Escopo compatível"], "gaps": ["Modalidade presencial"], '
        '"summary": "Ótima compatibilidade via Ollama"}'
    )
    mock_client.chat.return_value = mock_response

    mock_model_obj = MagicMock()
    mock_model_obj.model = "qwen2.5:3b"
    mock_client.list.return_value = MagicMock(models=[mock_model_obj])

    provider = OllamaProvider(model="qwen2.5:3b", client=mock_client)

    job = Job(
        id="job-ollama-test",
        title="Analista Administrativo Pleno",
        company="Empresa Local",
        location="São Paulo, SP",
        work_model="Híbrido",
        contract_type="CLT",
        application_url="https://www.linkedin.com/jobs/view/123456789/",
        checked_at="2026-11-11T20:00:00",
        description="Rotinas administrativas gerais.",
        requirements=["Excel", "Gestão de documentos"],
        responsibilities=["Emissão de relatórios"],
    )
    profile = CandidateProfile(
        full_name="Candidato Teste",
        location="São Paulo, SP",
        linkedin_url="https://www.linkedin.com/in/candidato-teste",
        education="Ensino Médio Completo",
        contract_availability=["CLT", "PJ"],
        has_active_mei=True,
        preferred_work_model="Híbrido",
        priority_areas=["Administrativo", "Financeiro"],
        target_levels=["Assistente", "Júnior", "Pleno"],
        target_roles_primary=["Analista Administrativo"],
        target_roles_expanded=["Assistente Administrativo"],
        excluded_roles_and_levels=["Gerente", "Diretor"],
        proven_competencies=["Excel intermediário", "Rotinas administrativas"],
        behavioral_competencies=["Organização", "Pontualidade"],
        office_proficiency="Pacote Office intermediário",
        experiences=[],
        pending_confirmations=[],
    )

    res = evaluate_job_match(job, profile, llm_provider=provider)
    assert res.match_score == 85.0
    assert res.match_level == MatchLevel.HIGH
    assert "Escopo compatível" in res.strengths
    assert "Ótima compatibilidade via Ollama" in res.summary
