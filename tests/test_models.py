"""Testes de estrutura (Etapa 1), modelos de domínio e perfil curricular (Etapa 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from linkedin_researcher.analysis.curriculum_profile import (
    build_profile_and_recruiters_from_cv_and_md,
    extract_curriculum_pdf_text,
    get_default_candidate_profile,
    load_candidate_additional_info,
    load_candidate_profile,
    parse_recruiters_from_markdown,
)
from linkedin_researcher.cli import run_doctor
from linkedin_researcher.config import AppConfig, validate_curriculum_pdf_extension
from linkedin_researcher.models import (
    Company,
    Job,
    JobStatus,
    MatchLevel,
    Recruiter,
    ReplyStatus,
    ReviewStatus,
    SuggestedMessage,
)


def test_stage1_project_structure_and_files(project_root: Path, app_config: AppConfig) -> None:
    """Verifica que a estrutura obrigatória da Etapa 1 e a padronização .agents existem."""
    readme_path = project_root / "README.md"
    assert readme_path.exists(), "Arquivo README.md não encontrado."
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "LinkedIn Researcher & Career Assistant" in readme_content

    required_paths = [
        project_root / "AGENTS.md",
        project_root / "README.md",
        project_root / "pyproject.toml",
        project_root / ".env.example",
        project_root / ".gitignore",
        project_root / "docs" / "ARCHITECTURE.md",
        project_root / "docs" / "PLAYWRIGHT_GUIDELINES.md",
        project_root / "docs" / "PYTHON_GUIDELINES.md",
        project_root / "docs" / "SECURITY_AND_PRIVACY.md",
        project_root / "docs" / "SKILLS.md",
        project_root / ".agents" / "skills" / "playwright-cli" / "SKILL.md",
        project_root / ".agents" / "skills" / "playwright-python" / "SKILL.md",
        project_root / ".agents" / "skills" / "developing-with-streamlit" / "SKILL.md",
        project_root / ".agents" / "rules" / "01-project-context-and-ethics.md",
        project_root / ".agents" / "rules" / "02-playwright-and-linkedin.md",
        project_root / ".agents" / "rules" / "03-python-and-architecture.md",
        project_root / ".agents" / "agents" / "linkedin-researcher.md",
        project_root / ".agents" / "agents" / "job-matcher.md",
        project_root / ".agents" / "agents" / "career-message-writer.md",
        app_config.recruiters_file,
        app_config.companies_file,
        app_config.jobs_file,
        app_config.contacts_file,
    ]
    for path in required_paths:
        assert path.exists(), f"Arquivo obrigatório ausente: {path}"


def test_cli_doctor_succeeds() -> None:
    """Valida que o comando doctor da CLI executa com sucesso e popula os recrutadores."""
    assert run_doctor() == 0


def test_recruiter_model_validation() -> None:
    rec = Recruiter(
        id="rec-test",
        name="  Caesar Cesar  ",
        linkedin_url="https://www.linkedin.com/in/caesarcc",
        current_title="Engenheiro de Dados | Cloudera CDP/CDH | Spark | Airflow | Python e SQL",
        location="Porto Alegre, RS",
    )
    assert rec.name == "Caesar Cesar"
    assert rec.current_company == "Pendente"
    assert rec.company_verified is False

    with pytest.raises(ValidationError):
        Recruiter(
            id="rec-invalid-url",
            name="Teste",
            linkedin_url="ftp://invalid-url",
            current_title="RH",
            location="Porto Alegre, RS",
        )


def test_company_and_job_model_validation() -> None:
    comp = Company(
        id="comp-01",
        name="Facilita RH",
        linkedin_url="https://www.linkedin.com/company/facilita-rh",
        source_urls=["https://www.linkedin.com/company/facilita-rh"],
    )
    assert comp.industry == "a confirmar"

    job = Job(
        id="job-01",
        title="Assistente Administrativo Financeiro",
        company="Empresa Exemplo",
        application_url="https://www.linkedin.com/jobs/view/123456",
        checked_at="2026-11-11T00:15:00",
        match_score=88.5,
        match_level=MatchLevel.HIGH,
    )
    assert job.status == JobStatus.IDENTIFIED
    assert "https://www.linkedin.com/jobs/view/123456" in job.source_urls

    with pytest.raises(ValidationError):
        Job(
            id="job-invalid-score",
            title="Assistente Financeiro",
            company="Empresa Exemplo",
            application_url="https://www.linkedin.com/jobs/view/123456",
            checked_at="2026-11-11T00:15:00",
            match_score=120.0,
        )


def test_suggested_message_defaults_to_human_control() -> None:
    msg = SuggestedMessage(
        id="msg-01",
        recruiter_id="rec-01-caesar-cesar",
        context="Primeiro contato sobre oportunidades técnicas em dados",
        message_text="Olá, Caesar, tudo bem? Estou em busca de novos desafios...",
        created_at="2026-11-11T00:15:00",
    )
    assert msg.review_status == ReviewStatus.PENDING_REVIEW
    assert msg.sent_by_user is False
    assert msg.sent_at is None
    assert msg.reply_status == ReplyStatus.NOT_SENT


def test_candidate_curriculum_profile_and_pdf_consistency(app_config: AppConfig) -> None:
    profile = load_candidate_profile(app_config)
    assert profile.full_name != ""
    assert get_default_candidate_profile().full_name != ""
    assert len(profile.target_levels) > 0
    assert len(profile.experiences) > 0

    if app_config.curriculum_path.exists():
        pdf_text = extract_curriculum_pdf_text(app_config.curriculum_path)
        assert len(pdf_text) > 50


def test_configurable_candidate_profile_loading(app_config: AppConfig) -> None:
    profile = load_candidate_profile(app_config)
    assert profile.full_name != ""
    assert len(profile.priority_areas) > 0
    assert len(profile.target_roles_primary) > 0

    # Valida carregamento opcional de diretrizes adicionais
    additional_info = load_candidate_additional_info(app_config)
    if app_config.candidate_additional_info_file.exists():
        assert additional_info is not None
        assert profile.additional_info is not None


def test_reject_docx_curriculum_extension() -> None:
    """Garante que arquivos Word (.docx ou .doc) sejam estritamente rejeitados."""
    with pytest.raises(ValueError, match="Arquivos Word.*não são permitidos"):
        validate_curriculum_pdf_extension(Path("curriculum/curriculo.docx"))

    with pytest.raises(ValueError, match="Arquivos Word.*não são permitidos"):
        validate_curriculum_pdf_extension(Path("curriculum/curriculo.doc"))

    with pytest.raises(ValueError, match="exclusivamente currículos no formato .pdf"):
        validate_curriculum_pdf_extension(Path("curriculum/curriculo.txt"))

    # Arquivo .pdf válido não deve lançar exceção
    validate_curriculum_pdf_extension(Path("curriculum/curriculo.pdf"))


def test_parse_recruiters_from_markdown_table_and_bullets() -> None:
    """Verifica extração correta de recrutadores em formato tabela e formato lista."""
    sample_md = """
    # Informações do Candidato

    ## 7. Recrutadores para Pesquisa

    | Nome | Cargo / Headline no LinkedIn | Local | Empresa Atual | Foco de Recrutamento |
    | :--- | :--- | :--- | :--- | :--- |
    | Caesar Cesar | Engenheiro de Dados | Porto Alegre, RS | Vert Analytics | Dados, Python |
    | Caesar Cesar (Consultor) | Consultor | Porto Alegre, RS | Tech Analytics | Cloud |

    Outras notas...

    ## Mais Recrutadores em Lista
    - **Caesar Cesar (Tech Lead)**: Tech Lead de Dados | Porto Alegre, RS | Pendente | Big Data
    """
    recruiters = parse_recruiters_from_markdown(sample_md)
    assert len(recruiters) == 3
    assert recruiters[0].id == "rec-01-caesar-cesar"
    assert recruiters[0].name == "Caesar Cesar"
    assert recruiters[0].current_company == "Vert Analytics"
    assert recruiters[0].location == "Porto Alegre, RS"
    assert recruiters[1].id == "rec-02-caesar-cesar-consultor"
    assert recruiters[1].name == "Caesar Cesar (Consultor)"
    assert recruiters[2].id == "rec-03-caesar-cesar-tech-lead"
    assert recruiters[2].name == "Caesar Cesar (Tech Lead)"


def test_build_profile_and_recruiters_execution(app_config: AppConfig, tmp_path: Path) -> None:
    """Testa a geração de arquivos JSON a partir do PDF e de um arquivo MD."""
    if not app_config.curriculum_path.exists():
        pytest.skip("Currículo PDF de teste não encontrado.")

    temp_md = tmp_path / "candidato_teste.md"
    temp_md.write_text(
        "# Informações Adicionais\n\n"
        "## 7. Recrutadores para Pesquisa\n"
        "| Nome | Cargo | Local | Empresa | Foco |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        "| Caesar Cesar | Engenheiro de Dados | Porto Alegre, RS | Vert Analytics | Python |\n",
        encoding="utf-8",
    )

    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    test_cfg = AppConfig(
        project_root=tmp_path,
        user_data_dir=tmp_path / ".playwright-profile",
        headless=True,
        default_timeout_ms=1000,
        navigation_timeout_ms=2000,
        min_action_delay_sec=0.0,
        max_action_delay_sec=0.0,
        data_dir=test_data_dir,
        curriculum_path=app_config.curriculum_path,
        candidate_profile_path=test_data_dir / "perfil_candidato.json",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        log_level="INFO",
        candidate_additional_info_path=temp_md,
    )

    profile, recruiters = build_profile_and_recruiters_from_cv_and_md(
        pdf_path=app_config.curriculum_path,
        md_path=temp_md,
        config=test_cfg,
    )
    assert profile.full_name != ""
    assert len(recruiters) == 1
    assert recruiters[0].name == "Caesar Cesar"
    assert recruiters[0].id == "rec-01-caesar-cesar"
    assert test_cfg.candidate_profile_file.exists()
    assert test_cfg.recruiters_file.exists()
