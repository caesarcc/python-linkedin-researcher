"""Testes da camada de persistência JSON e deduplicação (Etapa 2)."""

from __future__ import annotations

from pathlib import Path

from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Company, Job, Recruiter, SuggestedMessage
from linkedin_researcher.storage import JsonStorage


def _make_temp_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    return AppConfig(
        project_root=tmp_path,
        user_data_dir=tmp_path / ".playwright-profile",
        headless=True,
        default_timeout_ms=5000,
        navigation_timeout_ms=10000,
        min_action_delay_sec=0.1,
        max_action_delay_sec=0.2,
        data_dir=data_dir,
        curriculum_path=tmp_path / "curriculum" / "curriculo.pdf",
        candidate_profile_path=data_dir / "perfil_candidato.json",
        candidate_additional_info_path=data_dir / "informacoes_adicionais.md",
        output_dir=output_dir,
        logs_dir=logs_dir,
        log_level="INFO",
    )


def _sample_recruiters() -> list[Recruiter]:
    return [
        Recruiter(
            id="rec-01-caesar-cesar",
            name="Caesar Cesar",
            linkedin_url="https://www.linkedin.com/in/caesarcc/",
            current_title="Engenheiro de Dados | Cloudera CDP/CDH | Spark | Airflow | Python e SQL",
            current_company="Vert Analytics",
            location="Porto Alegre, RS",
            recruitment_focus=["Engenharia de Dados", "Big Data", "Python"],
            company_verified=True,
            professional_context="Perfil no LinkedIn https://www.linkedin.com/in/caesarcc/",
        ),
        Recruiter(
            id="rec-02-caesar-cesar-consultoria",
            name="Caesar Cesar (Consultor)",
            linkedin_url="https://www.linkedin.com/in/caesarcc/",
            current_title="Consultor de Dados e Tecnologia",
            current_company="Pendente",
            location="Porto Alegre, RS",
            recruitment_focus=["Cloud Analytics", "Data Platforms"],
            company_verified=False,
            professional_context="a confirmar",
        ),
    ]


def test_seed_initial_recruiters(tmp_path: Path) -> None:
    cfg = _make_temp_config(tmp_path)
    storage = JsonStorage(cfg)

    # Inicialmente vazio
    assert storage.list_recruiters() == []

    # Cadastra recrutadores fornecidos externamente (ex.: do markdown)
    seeded = storage.seed_initial_recruiters(_sample_recruiters())
    assert len(seeded) == 2
    assert seeded[0].name == "Caesar Cesar"

    # Executar novamente não deve duplicar registros
    seeded_again = storage.seed_initial_recruiters(_sample_recruiters())
    assert len(seeded_again) == 2


def test_recruiter_deduplication_by_name_location_and_url(tmp_path: Path) -> None:
    cfg = _make_temp_config(tmp_path)
    storage = JsonStorage(cfg)
    storage.seed_initial_recruiters(_sample_recruiters())

    # Atualizar Caesar Cesar informando URL e empresa verificada com ID diferente
    updated_caesar = Recruiter(
        id="novo-id-temporario",
        name="  caesar   cesar ",
        linkedin_url="https://www.linkedin.com/in/caesarcc/?trk=123",
        current_title="Lead Data Engineer",
        current_company="Vert Analytics",
        location="porto alegre, rs",
        company_verified=True,
        profile_checked_at="2026-11-11T00:20:00",
        source_url="https://www.linkedin.com/in/caesarcc/",
    )
    saved = storage.upsert_recruiter(updated_caesar)

    # Deve preservar o ID original e não criar novo registro
    assert saved.id == "rec-01-caesar-cesar"
    all_recruiters = storage.list_recruiters()
    assert len(all_recruiters) == 2
    caesar_db = storage.get_recruiter("rec-01-caesar-cesar")
    assert caesar_db is not None
    assert caesar_db.company_verified is True
    assert caesar_db.current_company == "Vert Analytics"

    # Nova atualização agora coincidindo pela URL normalizada
    updated_by_url = Recruiter(
        id="outro-id",
        name="Caesar C.",
        linkedin_url="https://www.linkedin.com/in/caesarcc",
        current_title="Staff Data Engineer",
        current_company="Vert Analytics",
        location="Porto Alegre, RS",
        company_verified=True,
    )
    saved_url = storage.upsert_recruiter(updated_by_url)
    assert saved_url.id == "rec-01-caesar-cesar"
    assert len(storage.list_recruiters()) == 2


def test_company_and_job_deduplication(tmp_path: Path) -> None:
    cfg = _make_temp_config(tmp_path)
    storage = JsonStorage(cfg)

    comp1 = Company(
        id="comp-01",
        name="Facilita RH",
        linkedin_url="https://www.linkedin.com/company/facilita-rh/",
    )
    comp2 = Company(
        id="comp-duplicada",
        name="  facilita   rh ",
        industry="Recursos Humanos",
        verified_at="2026-11-11T00:20:00",
    )
    storage.upsert_company(comp1)
    saved_comp = storage.upsert_company(comp2)
    assert saved_comp.id == "comp-01"
    assert len(storage.list_companies()) == 1
    assert storage.get_company("comp-01").industry == "Recursos Humanos"

    job1 = Job(
        id="job-01",
        title="Assistente Financeiro",
        company="Facilita RH",
        location="Porto Alegre, RS",
        application_url="https://www.linkedin.com/jobs/view/999888/?refId=abc",
        checked_at="2026-11-11T00:20:00",
    )
    job2 = Job(
        id="job-dup-url",
        title="Assistente Financeiro (Remoto)",
        company="Facilita RH",
        location="Porto Alegre, RS",
        work_model="Remoto",
        application_url="https://www.linkedin.com/jobs/view/999888",
        checked_at="2026-11-11T00:25:00",
    )
    storage.upsert_job(job1)
    saved_job = storage.upsert_job(job2)
    assert saved_job.id == "job-01"
    assert len(storage.list_jobs()) == 1
    assert storage.get_job("job-01").work_model == "Remoto"


def test_suggested_messages_persistence(tmp_path: Path) -> None:
    cfg = _make_temp_config(tmp_path)
    storage = JsonStorage(cfg)

    msg = SuggestedMessage(
        id="msg-01",
        recruiter_id="rec-01-caesar-cesar",
        context="Abordagem inicial sobre oportunidades em engenharia de dados e analytics",
        message_text="Olá, Caesar, tudo bem? Gostaria de me conectar...",
        created_at="2026-11-11T00:20:00",
    )
    storage.upsert_message(msg)
    msgs = storage.list_messages(recruiter_id="rec-01-caesar-cesar")
    assert len(msgs) == 1
    assert msgs[0].sent_by_user is False
