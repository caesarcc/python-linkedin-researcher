"""Testes do gerador de mensagens personalizadas sem envio automático — Etapa 5."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from linkedin_researcher.analysis.curriculum_profile import save_candidate_profile
from linkedin_researcher.config import AppConfig
from linkedin_researcher.messaging.message_generator import (
    MessageDraftResult,
    generate_all_drafts,
    generate_consolidated_report,
    generate_deterministic_draft,
    generate_message_draft,
    review_message,
)
from linkedin_researcher.models import (
    CandidateProfile,
    Company,
    ExperienceEntry,
    Job,
    MatchLevel,
    Recruiter,
    ReplyStatus,
    ReviewStatus,
    SuggestedMessage,
)
from linkedin_researcher.storage import JsonStorage


def _make_test_profile() -> CandidateProfile:
    """Cria perfil determinístico de teste."""
    return CandidateProfile(
        full_name="Candidata Exemplo",
        location="Porto Alegre, RS",
        linkedin_url="https://www.linkedin.com/in/candidata-exemplo",
        education="Ensino Médio e Técnico em Administração",
        contract_availability=["CLT", "PJ"],
        has_active_mei=False,
        preferred_work_model="Remoto ou Híbrido",
        priority_areas=["Administrativo", "Financeiro"],
        target_levels=["Assistente", "Júnior"],
        target_roles_primary=["Assistente Administrativo", "Assistente Financeiro"],
        target_roles_expanded=["Assistente de Contas a Pagar", "Faturamento"],
        excluded_roles_and_levels=["Gerente", "Diretora", "Coordenadora"],
        proven_competencies=[
            "contas a pagar e receber",
            "conciliação bancária",
            "lançamento de notas fiscais",
            "planilhas em Excel",
        ],
        behavioral_competencies=["organização", "comunicação clara"],
        office_proficiency="Excel intermediário e Pacote Office",
        experiences=[
            ExperienceEntry(
                company="Empresa Sul Logística",
                period_pdf="01/2021 – 12/2024",
                role_in_pdf="Assistente Administrativo",
                positioning_role="Assistente Administrativo",
                is_current=False,
                activities=["Conciliação bancária e emissão de notas fiscais."],
            )
        ],
        pending_confirmations=[],
    )


def test_generate_deterministic_draft_with_verified_company() -> None:
    """Valida rascunho em primeira pessoa quando o recrutador tem empresa confirmada."""
    profile = _make_test_profile()
    recruiter = Recruiter(
        id="rec-verif-01",
        name="Mariana Souza",
        linkedin_url="https://www.linkedin.com/in/mariana-souza",
        current_title="Talent Acquisition Specialist",
        current_company="Unidão Transportes",
        company_verified=True,
        location="Porto Alegre, RS",
        recruitment_focus=["Vagas Administrativas"],
    )

    result = generate_deterministic_draft(profile, recruiter)
    assert isinstance(result, MessageDraftResult)
    assert "Mariana" in result.message_text
    assert "Unidão Transportes" in result.message_text
    assert "Assistente Administrativo" in result.message_text
    assert "Candidata Exemplo" in result.message_text
    assert "networking" in result.tone_notes.lower()


def test_generate_deterministic_draft_with_pending_company() -> None:
    """Valida que recrutador com empresa pendente não tem vínculo afirmado na mensagem."""
    profile = _make_test_profile()
    recruiter = Recruiter(
        id="rec-pend-01",
        name="Carlos Eduardo",
        linkedin_url="https://www.linkedin.com/in/carlos-eduardo",
        current_title="Consultor de R&S",
        current_company="Pendente",
        company_verified=False,
        location="Porto Alegre, RS",
    )

    result = generate_deterministic_draft(profile, recruiter)
    assert "Carlos" in result.message_text
    assert "Pendente" not in result.message_text
    assert "Recrutamento & Seleção" in result.message_text
    assert "cautelosa" in result.tone_notes.lower()


def test_generate_deterministic_draft_with_linked_job() -> None:
    """Valida rascunho personalizado quando há uma vaga específica associada."""
    profile = _make_test_profile()
    recruiter = Recruiter(
        id="rec-job-01",
        name="Patrícia Lima",
        linkedin_url="https://www.linkedin.com/in/patricia-lima",
        current_title="Headhunter",
        location="Porto Alegre, RS",
    )
    job = Job(
        id="job-101",
        title="Assistente Financeiro Pleno",
        company="Distribuidora Delta",
        location="Porto Alegre, RS",
        work_model="Híbrido",
        application_url="https://www.linkedin.com/jobs/view/101",
        checked_at="2026-11-11T12:00:00",
    )

    result = generate_deterministic_draft(profile, recruiter, job=job)
    assert "Patrícia" in result.message_text
    assert "Assistente Financeiro Pleno" in result.message_text
    assert "Distribuidora Delta" in result.message_text


def test_message_creation_safety_and_file_generation(tmp_path: Path) -> None:
    """Garante que a mensagem NUNCA nasce enviada e grava arquivo Markdown de revisão."""
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
    save_candidate_profile(_make_test_profile(), config.candidate_profile_path)

    storage = JsonStorage(config)
    rec = Recruiter(
        id="rec-test-safe",
        name="Juliana Ramos",
        current_title="Tech & Corporate Recruiter",
        current_company="Grupo Varejo",
        company_verified=True,
        location="Porto Alegre, RS",
    )
    storage.seed_initial_recruiters([rec])

    # Gera o rascunho
    msg = generate_message_draft(config, recruiter_id="rec-test-safe", force_offline=True)

    # Invariantes de controle humano
    assert msg.review_status == ReviewStatus.PENDING_REVIEW
    assert msg.sent_by_user is False
    assert msg.sent_at is None
    assert msg.reply_status == ReplyStatus.NOT_SENT

    # Persistência em contatos.json
    stored_msgs = storage.list_messages(recruiter_id="rec-test-safe")
    assert len(stored_msgs) == 1
    assert stored_msgs[0].id == msg.id

    # Arquivo Markdown gerado
    md_file = out_dir / "mensagens" / "rec-test-safe.md"
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "CONTROLE HUMANO OBRIGATÓRIO" in content
    assert "**NUNCA** é enviada automaticamente" in content
    assert "Juliana Ramos" in content


def test_review_message_lifecycle(tmp_path: Path) -> None:
    """Valida ciclo de vida da revisão humana (aprovação, edição e marcação manual de envio)."""
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
    save_candidate_profile(_make_test_profile(), config.candidate_profile_path)
    storage = JsonStorage(config)

    initial_msg = SuggestedMessage(
        id="msg-rev-01",
        recruiter_id="rec-rev-01",
        context="Teste de revisão",
        message_text="Olá, mensagem inicial de teste.",
        created_at="2026-11-11T10:00:00",
        review_status=ReviewStatus.PENDING_REVIEW,
        sent_by_user=False,
        sent_at=None,
        reply_status=ReplyStatus.NOT_SENT,
    )
    storage.upsert_message(initial_msg)

    # 1. Usuário aprova a mensagem
    approved = review_message(
        config,
        message_id="msg-rev-01",
        status=ReviewStatus.APPROVED,
        notes="Aprovada sem ressalvas.",
    )
    assert approved.review_status == ReviewStatus.APPROVED
    assert approved.sent_by_user is False
    assert "Aprovada sem ressalvas" in approved.notes

    # 2. Usuário informa que enviou manualmente pelo LinkedIn
    sent = review_message(config, message_id="msg-rev-01", mark_sent=True)
    assert sent.sent_by_user is True
    assert sent.sent_at is not None
    assert sent.reply_status == ReplyStatus.WAITING_REPLY


def test_generate_all_drafts_and_cache(tmp_path: Path) -> None:
    """Valida geração em lote para todos os recrutadores com suporte a cache e refresh."""
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
    save_candidate_profile(_make_test_profile(), config.candidate_profile_path)
    storage = JsonStorage(config)

    r1 = Recruiter(
        id="rec-01",
        name="Recrutador Um",
        current_title="RH",
        current_company="Empresa 1",
        location="Porto Alegre, RS",
    )
    r2 = Recruiter(
        id="rec-02",
        name="Recrutador Dois",
        current_title="Headhunter",
        current_company="Empresa 2",
        location="Porto Alegre, RS",
    )
    storage.seed_initial_recruiters([r1, r2])

    drafts = generate_all_drafts(config, force_offline=True)
    assert len(drafts) == 2
    assert {d.recruiter_id for d in drafts} == {"rec-01", "rec-02"}

    # Modifica texto em cache
    mod = drafts[0].model_copy(update={"message_text": "Texto alterado em cache"})
    storage.upsert_message(mod)

    # Sem refresh: mantém cache
    cached = generate_all_drafts(config, refresh=False, force_offline=True)
    assert cached[0].message_text == "Texto alterado em cache"

    # Com refresh: regera
    refreshed = generate_all_drafts(config, refresh=True, force_offline=True)
    assert refreshed[0].message_text != "Texto alterado em cache"


def test_generate_gemini_draft_with_mock(tmp_path: Path) -> None:
    """Valida enriquecimento de mensagem via mock da API Gemini."""
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
        gemini_enabled=True,
        has_gemini_api_key=True,
    )
    save_candidate_profile(_make_test_profile(), config.candidate_profile_path)
    storage = JsonStorage(config)

    rec = Recruiter(
        id="rec-gemini",
        name="Fernanda Silva",
        current_title="Talent Acquisition Leader",
        current_company="Tech Brasil",
        company_verified=True,
        location="Porto Alegre, RS",
    )
    storage.seed_initial_recruiters([rec])

    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = (
        '{"context": "Abordagem refinada via IA para Tech Brasil", '
        '"message_text": "Olá, Fernanda, tudo bem? '
        'Acompanho com admiração o trabalho na Tech Brasil...", '
        '"tone_notes": "Tom refinado e cordial."}'
    )
    mock_client.interactions.create.return_value = mock_interaction

    msg = generate_message_draft(
        config=config,
        recruiter_id="rec-gemini",
        client=mock_client,
    )
    assert msg.context == "Abordagem refinada via IA para Tech Brasil"
    assert "Fernanda" in msg.message_text
    assert "Tech Brasil" in msg.message_text


def test_generate_consolidated_report(tmp_path: Path) -> None:
    """Valida a geração do relatório executivo consolidado em output/relatorio_consolidado.md."""
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
    save_candidate_profile(_make_test_profile(), config.candidate_profile_path)
    storage = JsonStorage(config)

    # Insere dados representativos
    rec = Recruiter(
        id="rec-rep-01",
        name="Roberto Santos",
        current_title="RH Gerencial",
        current_company="Sul Alimentos",
        company_verified=True,
        location="Porto Alegre, RS",
    )
    storage.seed_initial_recruiters([rec])

    comp = Company(
        id="comp-sul-alimentos",
        name="Sul Alimentos",
        location="Porto Alegre, RS",
        industry="Alimentos e Bebidas",
    )
    storage.upsert_company(comp)

    job = Job(
        id="job-rep-01",
        title="Assistente Financeiro",
        company="Sul Alimentos",
        location="Porto Alegre, RS",
        work_model="Híbrido",
        application_url="https://www.linkedin.com/jobs/view/999",
        checked_at="2026-11-11T12:00:00",
        match_score=85.0,
        match_level=MatchLevel.HIGH,
    )
    storage.upsert_job(job)

    # Gera rascunho de mensagem
    generate_message_draft(config, recruiter_id="rec-rep-01", force_offline=True)

    # Gera relatório consolidado
    report_path = generate_consolidated_report(config)
    assert report_path.exists()

    content = report_path.read_text(encoding="utf-8")
    assert "Relatório Consolidado de Prospecção e Carreira no LinkedIn" in content
    assert "1. Resumo Executivo do Candidato" in content
    assert "2. Oportunidades Identificadas e Ranqueadas" in content
    assert "3. Mapeamento de Recrutadores e Contatos" in content
    assert "4. Empresas Mapeadas" in content
    assert "5. Rascunhos de Abordagem para Revisão Humana" in content
    assert "Roberto Santos" in content
    assert "Sul Alimentos" in content
    assert "Assistente Financeiro" in content
