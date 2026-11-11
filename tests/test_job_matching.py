"""Testes do motor de análise, matching e ranking de vagas — Etapa 4."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from linkedin_researcher.analysis.curriculum_profile import save_candidate_profile
from linkedin_researcher.analysis.job_matching import (
    JobMatchingResult,
    check_role_exclusion,
    evaluate_deterministic_match,
    evaluate_job_match,
    match_all_jobs,
    match_job,
)
from linkedin_researcher.analysis.ranking import (
    filter_excluded_jobs,
    filter_jobs_by_match_level,
    filter_jobs_by_work_model,
    get_top_opportunities,
    rank_jobs,
)
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import (
    CandidateProfile,
    ExperienceEntry,
    Job,
    JobStatus,
    MatchLevel,
)
from linkedin_researcher.storage import JsonStorage


def _make_sample_candidate_profile() -> CandidateProfile:
    """Cria um perfil de candidato determinístico para os testes."""
    return CandidateProfile(
        full_name="Candidato Teste",
        location="Porto Alegre, RS",
        linkedin_url="https://www.linkedin.com/in/candidato-teste",
        education="Ensino Médio Completo",
        contract_availability=["CLT", "PJ"],
        has_active_mei=True,
        preferred_work_model="Remoto ou Híbrido (Porto Alegre e Região Metropolitana)",
        priority_areas=["Administrativo", "Financeiro", "Back Office", "Faturamento"],
        target_levels=["Assistente", "Auxiliar", "Júnior"],
        target_roles_primary=["Assistente Administrativo", "Assistente Financeiro"],
        target_roles_expanded=[
            "Assistente de Faturamento",
            "Assistente de Contas a Pagar",
            "Auxiliar Financeiro",
        ],
        excluded_roles_and_levels=[
            "Gerente",
            "Diretor",
            "Coordenador",
            "Supervisor",
            "Head",
        ],
        proven_competencies=[
            "contas a pagar e receber",
            "conciliacao bancaria",
            "emissao de notas fiscais",
            "faturamento",
            "controles em planilhas",
            "rotinas administrativas",
        ],
        behavioral_competencies=["organizacao", "comunicacao assertiva", "pontualidade"],
        office_proficiency="Pacote Office intermediário (Excel, Word e Outlook)",
        experiences=[
            ExperienceEntry(
                company="Empresa Sul Logística",
                period_pdf="01/2021 – 12/2024",
                role_in_pdf="Assistente Administrativo",
                positioning_role="Assistente Administrativo",
                is_current=False,
                activities=[
                    "Rotinas de contas a pagar, conciliação e lançamento de notas fiscais.",
                    "Controle de planilhas financeiras e atendimento a fornecedores.",
                ],
            )
        ],
        pending_confirmations=[],
    )


def test_job_matching_high_affinity_role() -> None:
    """Valida cálculo de alta aderência para vaga com escopo e localidade alinhados."""
    profile = _make_sample_candidate_profile()
    job = Job(
        id="job-sample-high",
        title="Assistente Administrativo Financeiro",
        company="Distribuidora Gaúcha",
        location="Porto Alegre, RS",
        work_model="Híbrido",
        contract_type="CLT",
        salary_range="R$ 2.500 a R$ 3.000",
        description="Atuar com conciliação bancária, contas a pagar e planilhas em Excel.",
        requirements=[
            "Ensino médio completo",
            "Excel intermediário",
            "Experiência em rotinas financeiras",
        ],
        responsibilities=["Conciliação de extratos", "Emissão de notas fiscais e relatórios"],
        application_url="https://www.linkedin.com/jobs/view/1001",
        checked_at="2026-11-11T12:00:00",
    )

    result = evaluate_deterministic_match(job, profile)
    assert result.match_score >= 75.0
    assert result.match_level == MatchLevel.HIGH
    assert len(result.strengths) >= 3
    # Confirma que os pontos fortes capturam título e competências
    assert any("primário" in s.lower() or "compatível" in s.lower() for s in result.strengths)
    assert any("competências comprovadas" in s.lower() for s in result.strengths)


def test_job_matching_excluded_role_prefilter() -> None:
    """Verifica descarte e baixa pontuação pelo pré-filtro local para cargos de liderança."""
    profile = _make_sample_candidate_profile()
    job_gerente = Job(
        id="job-gerente",
        title="Gerente Administrativo e Financeiro",
        company="Grupo Varejo",
        location="Porto Alegre, RS",
        work_model="Presencial",
        contract_type="CLT",
        description="Gestão de equipes, liderança de departamentos e planejamento estratégico.",
        application_url="https://www.linkedin.com/jobs/view/1002",
        checked_at="2026-11-11T12:00:00",
    )

    term = check_role_exclusion(job_gerente.title, profile.excluded_roles_and_levels)
    assert term == "Gerente"

    result = evaluate_deterministic_match(job_gerente, profile)
    assert result.match_score <= 25.0
    assert result.match_level == MatchLevel.LOW
    assert any("excluído" in g.lower() for g in result.gaps)
    assert len(result.strengths) == 0


def test_job_matching_location_penalty_on_onsite() -> None:
    """Valida penalização severa quando a vaga é 100% presencial em outra praça distante."""
    profile = _make_sample_candidate_profile()
    job_sp = Job(
        id="job-sp-presencial",
        title="Assistente Administrativo",
        company="Paulista Tech",
        location="São Paulo, SP",
        work_model="Presencial",
        contract_type="CLT",
        description="Atividades operacionais de escritório na sede de São Paulo.",
        application_url="https://www.linkedin.com/jobs/view/1003",
        checked_at="2026-11-11T12:00:00",
    )

    result = evaluate_deterministic_match(job_sp, profile)
    # Deve ser penalizada por estar em SP presencial
    has_loc_gap = any(
        "fora da localidade" in g.lower() or "difere da residência" in g.lower()
        for g in result.gaps
    )
    assert has_loc_gap
    assert result.match_score < 75.0


def test_job_matching_remote_neutralizes_location() -> None:
    """Valida que uma vaga 100% remota não sofre penalização geográfica."""
    profile = _make_sample_candidate_profile()
    job_remote = Job(
        id="job-remote-bh",
        title="Assistente Financeiro",
        company="Fintech Brasil",
        location="Belo Horizonte, MG",
        work_model="Remoto",
        contract_type="CLT",
        description="Atividades financeiras totalmente à distância.",
        application_url="https://www.linkedin.com/jobs/view/1004",
        checked_at="2026-11-11T12:00:00",
    )

    result = evaluate_deterministic_match(job_remote, profile)
    assert any("sem restrição geográfica" in s.lower() for s in result.strengths)
    assert any("remota" in s.lower() for s in result.strengths)
    assert result.match_score >= 70.0


def test_ranking_and_filters() -> None:
    """Valida ordenação por relevância, score e filtragem por nível e modalidade."""
    profile = _make_sample_candidate_profile()

    job1 = Job(
        id="j1",
        title="Assistente Administrativo",
        company="C1",
        application_url="https://www.linkedin.com/jobs/view/1",
        checked_at="2026-11-11T10:00:00",
        match_score=85.0,
        match_level=MatchLevel.HIGH,
        work_model="Remoto",
    )
    job2 = Job(
        id="j2",
        title="Auxiliar Financeiro",
        company="C2",
        application_url="https://www.linkedin.com/jobs/view/2",
        checked_at="2026-11-11T11:00:00",
        match_score=68.0,
        match_level=MatchLevel.MEDIUM,
        work_model="Híbrido",
    )
    job3 = Job(
        id="j3",
        title="Gerente Financeiro",
        company="C3",
        application_url="https://www.linkedin.com/jobs/view/3",
        checked_at="2026-11-11T09:00:00",
        match_score=20.0,
        match_level=MatchLevel.LOW,
        work_model="Presencial",
    )

    all_jobs = [job3, job1, job2]
    ranked = rank_jobs(all_jobs)
    assert [j.id for j in ranked] == ["j1", "j2", "j3"]

    high_only = filter_jobs_by_match_level(all_jobs, min_level=MatchLevel.HIGH)
    assert len(high_only) == 1
    assert high_only[0].id == "j1"

    med_and_above = filter_jobs_by_match_level(all_jobs, min_level=MatchLevel.MEDIUM)
    assert len(med_and_above) == 2
    assert {j.id for j in med_and_above} == {"j1", "j2"}

    remote_jobs = filter_jobs_by_work_model(all_jobs, allowed_models=["Remoto"])
    assert len(remote_jobs) == 1
    assert remote_jobs[0].id == "j1"

    excluded_filtered = filter_excluded_jobs(all_jobs, profile)
    assert "j3" not in [j.id for j in excluded_filtered]

    top2 = get_top_opportunities(all_jobs, profile, limit=2)
    assert len(top2) == 2
    assert top2[0].id == "j1"
    assert top2[1].id == "j2"


def test_match_job_storage_cache_and_refresh(tmp_path: Path) -> None:
    """Valida persistência da análise em JSON, respeito ao cache e forçamento com refresh."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)

    config = AppConfig(
        project_root=tmp_path,
        user_data_dir=tmp_path / ".profile",
        headless=True,
        default_timeout_ms=1000,
        navigation_timeout_ms=1000,
        min_action_delay_sec=0.1,
        max_action_delay_sec=0.2,
        data_dir=data_dir,
        curriculum_path=tmp_path / "curriculum" / "cv.pdf",
        candidate_profile_path=data_dir / "perfil_candidato.json",
        output_dir=out_dir,
        logs_dir=tmp_path / "logs",
        log_level="INFO",
        gemini_enabled=False,
    )
    save_candidate_profile(_make_sample_candidate_profile(), config.candidate_profile_path)

    storage = JsonStorage(config)
    sample_job = Job(
        id="job-cache-test",
        title="Assistente de Contas a Pagar",
        company="Empresa Teste",
        location="Porto Alegre, RS",
        work_model="Híbrido",
        contract_type="CLT",
        description="Rotinas de faturamento e conciliação bancária.",
        application_url="https://www.linkedin.com/jobs/view/777",
        checked_at="2026-11-11T12:00:00",
    )
    storage.upsert_job(sample_job)

    # 1. Executa avaliação inicial
    analyzed = match_job(config, job_id="job-cache-test", force_offline=True)
    assert analyzed.status == JobStatus.ANALYZED
    assert analyzed.match_score is not None
    original_score = analyzed.match_score

    # 2. Modifica artificialmente o score para testar o cache
    cached_override = analyzed.model_copy(update={"match_score": 99.5})
    storage.upsert_job(cached_override)

    # Sem refresh: deve manter o valor em cache
    from_cache = match_job(config, job_id="job-cache-test", refresh=False, force_offline=True)
    assert from_cache.match_score == 99.5

    # Com refresh: deve recalcular
    refreshed = match_job(config, job_id="job-cache-test", refresh=True, force_offline=True)
    assert refreshed.match_score == original_score


def test_evaluate_job_match_with_gemini_mock() -> None:
    """Verifica integração e parsing com structured output da API Gemini via mock."""
    profile = _make_sample_candidate_profile()
    job = Job(
        id="job-gemini-mock",
        title="Assistente Financeiro",
        company="Empresa Gemini",
        location="Porto Alegre, RS",
        application_url="https://www.linkedin.com/jobs/view/888",
        checked_at="2026-11-11T12:00:00",
    )

    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = (
        '{"match_score": 88.0, "match_level": "Alta aderência", '
        '"strengths": ["Experiência sólida em rotinas financeiras"], '
        '"gaps": ["Modalidade de trabalho a confirmar"], '
        '"summary": "Forte afinidade com as atividades."}'
    )
    mock_client.interactions.create.return_value = mock_interaction

    config = AppConfig(
        project_root=Path("."),
        user_data_dir=Path(".profile"),
        headless=True,
        default_timeout_ms=1000,
        navigation_timeout_ms=1000,
        min_action_delay_sec=0.1,
        max_action_delay_sec=0.2,
        data_dir=Path("data"),
        curriculum_path=Path("curriculum/cv.pdf"),
        candidate_profile_path=Path("data/perfil_candidato.json"),
        output_dir=Path("output"),
        logs_dir=Path("logs"),
        log_level="INFO",
        gemini_enabled=True,
        has_gemini_api_key=True,
    )

    res = evaluate_job_match(job, profile, config=config, gemini_client=mock_client)
    assert isinstance(res, JobMatchingResult)
    assert res.match_score == 88.0
    assert res.match_level == MatchLevel.HIGH
    assert "rotinas financeiras" in res.strengths[0]


def test_match_all_jobs_execution(tmp_path: Path) -> None:
    """Valida avaliação em lote de todas as vagas cadastradas com geração de relatório."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)

    config = AppConfig(
        project_root=tmp_path,
        user_data_dir=tmp_path / ".profile",
        headless=True,
        default_timeout_ms=1000,
        navigation_timeout_ms=1000,
        min_action_delay_sec=0.1,
        max_action_delay_sec=0.2,
        data_dir=data_dir,
        curriculum_path=tmp_path / "curriculum" / "cv.pdf",
        candidate_profile_path=data_dir / "perfil_candidato.json",
        output_dir=out_dir,
        logs_dir=tmp_path / "logs",
        log_level="INFO",
        gemini_enabled=False,
    )
    save_candidate_profile(_make_sample_candidate_profile(), config.candidate_profile_path)

    storage = JsonStorage(config)
    j1 = Job(
        id="job-batch-1",
        title="Assistente Administrativo",
        company="Empresa A",
        location="Porto Alegre, RS",
        work_model="Híbrido",
        application_url="https://www.linkedin.com/jobs/view/10",
        checked_at="2026-11-11T12:00:00",
    )
    j2 = Job(
        id="job-batch-2",
        title="Gerente Geral",
        company="Empresa B",
        location="Porto Alegre, RS",
        application_url="https://www.linkedin.com/jobs/view/20",
        checked_at="2026-11-11T12:00:00",
    )
    storage.upsert_job(j1)
    storage.upsert_job(j2)

    evaluated = match_all_jobs(config, force_offline=True)
    assert len(evaluated) == 2
    ev_map = {j.id: j for j in evaluated}
    assert ev_map["job-batch-1"].match_level == MatchLevel.HIGH
    assert ev_map["job-batch-2"].match_level == MatchLevel.LOW

    # Confirma que o relatório de vagas foi gravado
    report_file = out_dir / "oportunidades" / "resumo_vagas.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "Assistente Administrativo" in content
    assert "Gerente Geral" in content
