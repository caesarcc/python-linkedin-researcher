"""Filtragem, classificação e ordenação de oportunidades — Etapa 4.

Fornece funções para ordenar e filtrar vagas avaliadas com base na aderência
ao currículo, modalidade de trabalho, nível de senioridade e preferências.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from linkedin_researcher.analysis.job_matching import check_role_exclusion
from linkedin_researcher.models import CandidateProfile, Job, MatchLevel

_MATCH_LEVEL_WEIGHT: dict[MatchLevel, int] = {
    MatchLevel.HIGH: 3,
    MatchLevel.MEDIUM: 2,
    MatchLevel.LOW: 1,
    MatchLevel.NOT_EVALUATED: 0,
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def rank_jobs(jobs: Iterable[Job], profile: CandidateProfile | None = None) -> list[Job]:
    """Ordena vagas prioritariamente por nível de aderência, score numérico e data.

    Critérios de ordenação:
    1. Peso do MatchLevel (Alta aderência > Média aderência > Baixa aderência > Não avaliada);
    2. Pontuação numérica (match_score) decrescente;
    3. Data da consulta (checked_at) mais recente.
    """
    job_list = list(jobs)

    def _sort_key(j: Job) -> tuple[int, float, str]:
        level_weight = _MATCH_LEVEL_WEIGHT.get(j.match_level, 0)
        score = j.match_score if j.match_score is not None else -1.0
        date_str = j.checked_at or ""
        return (level_weight, score, date_str)

    return sorted(job_list, key=_sort_key, reverse=True)


def filter_jobs_by_match_level(
    jobs: Iterable[Job],
    min_level: MatchLevel = MatchLevel.MEDIUM,
) -> list[Job]:
    """Filtra vagas com nível de aderência igual ou superior a min_level.

    Se min_level for HIGH, retorna apenas HIGH.
    Se min_level for MEDIUM, retorna HIGH e MEDIUM.
    Se min_level for LOW, retorna HIGH, MEDIUM e LOW.
    """
    min_weight = _MATCH_LEVEL_WEIGHT.get(min_level, 0)
    return [j for j in jobs if _MATCH_LEVEL_WEIGHT.get(j.match_level, 0) >= min_weight]


def filter_jobs_by_work_model(
    jobs: Iterable[Job],
    allowed_models: list[str],
) -> list[Job]:
    """Filtra vagas cuja modalidade contenha qualquer um dos modelos permitidos."""
    if not allowed_models:
        return list(jobs)

    clean_allowed = [_strip_accents(m).casefold() for m in allowed_models]
    results: list[Job] = []
    for j in jobs:
        model_clean = _strip_accents(j.work_model).casefold()
        if any(allowed in model_clean for allowed in clean_allowed):
            results.append(j)
    return results


def filter_excluded_jobs(
    jobs: Iterable[Job],
    profile: CandidateProfile,
) -> list[Job]:
    """Descarta vagas cujo título corresponda à lista de exclusão do candidato."""
    return [
        j for j in jobs
        if not check_role_exclusion(j.title, profile.excluded_roles_and_levels)
    ]


def get_top_opportunities(
    jobs: Iterable[Job],
    profile: CandidateProfile | None = None,
    limit: int = 5,
    min_level: MatchLevel = MatchLevel.MEDIUM,
) -> list[Job]:
    """Retorna as melhores oportunidades ranqueadas que atendem ao nível mínimo de aderência."""
    filtered = filter_jobs_by_match_level(jobs, min_level=min_level)
    if profile is not None:
        filtered = filter_excluded_jobs(filtered, profile)
    ranked = rank_jobs(filtered, profile)
    return ranked[:limit]
