"""Testes unitários da interface web Streamlit."""

from __future__ import annotations

import importlib
import io
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from linkedin_researcher.cli import build_parser, run_web
from linkedin_researcher.messaging.message_generator import review_message
from linkedin_researcher.models import (
    Company,
    Job,
    JobStatus,
    MatchLevel,
    Recruiter,
    ReviewStatus,
    SuggestedMessage,
)
from linkedin_researcher.storage import JsonStorage


def test_web_app_file_exists() -> None:
    """Valida existência do arquivo de entrada do Streamlit."""
    app_path = (
        Path(__file__).parent.parent
        / "src"
        / "linkedin_researcher"
        / "web"
        / "app.py"
    )
    assert app_path.exists()
    assert app_path.is_file()


def test_web_module_importable() -> None:
    """Valida importação limpa do módulo web sem erros de sintaxe ou dependências."""
    module = importlib.import_module("linkedin_researcher.web.app")
    assert hasattr(module, "main")
    assert hasattr(module, "render_sidebar")
    assert hasattr(module, "render_dashboard")
    assert hasattr(module, "render_jobs_tab")
    assert hasattr(module, "render_messages_tab")


def test_web_cli_parser_registered() -> None:
    """Valida se o subcomando 'web' foi registrado corretamente no parser da CLI."""
    parser = build_parser()
    args = parser.parse_args(["web", "--port", "8555", "--headless"])
    assert args.command == "web"
    assert args.port == 8555
    assert args.headless is True
    assert args.host == "localhost"


def test_run_web_command_invokes_streamlit(app_config, tmp_path: Path) -> None:
    """Valida que run_web inicia Streamlit via Popen e espelha toda a saída em arquivos de log."""
    isolated_cfg = replace(app_config, logs_dir=tmp_path / "logs")
    simulated_output = (
        "\x1b[32m2026-11-11 Uvicorn server started on 127.0.0.1:9000\x1b[0m\n"
        "2026-11-11 Uncaught app execution\n"
        "AttributeError: ALTA\n"
    )
    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO(simulated_output)
    mock_proc.wait.return_value = 0
    mock_proc.poll.return_value = 0

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        code = run_web(port=9000, host="127.0.0.1", headless=True, config=isolated_cfg)
        assert code == 0
        assert mock_popen.called
        cmd_args = mock_popen.call_args[0][0]
        assert "-m" in cmd_args
        assert "streamlit" in cmd_args
        assert "run" in cmd_args
        assert "--server.port" in cmd_args
        assert "9000" in cmd_args
        assert "--server.address" in cmd_args
        assert "127.0.0.1" in cmd_args
        assert "--server.headless" in cmd_args
        kwargs = mock_popen.call_args[1]
        assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"

    web_log = isolated_cfg.logs_dir / "web_server.log"
    app_log = isolated_cfg.logs_dir / "linkedin_researcher.log"
    assert web_log.exists()
    assert app_log.exists()

    web_text = web_log.read_text(encoding="utf-8")
    assert "Uvicorn server started on 127.0.0.1:9000" in web_text
    assert "\x1b[32m" not in web_text
    assert "Uncaught app execution" in web_text
    assert "AttributeError: ALTA" in web_text

    app_text = app_log.read_text(encoding="utf-8")
    assert "[WEB] 2026-11-11 Uncaught app execution" in app_text
    assert "[WEB] AttributeError: ALTA" in app_text


def test_app_config_aliases_for_web_integration(app_config) -> None:
    """Valida propriedades de compatibilidade em AppConfig usadas pela interface web."""
    assert app_config.playwright_profile_dir == app_config.user_data_dir
    assert app_config.curriculum_pdf_path == app_config.curriculum_path
    assert app_config.additional_info_path == app_config.candidate_additional_info_path


def test_developing_with_streamlit_skill_discovery() -> None:
    """Valida que o utilitário discover.py da skill developing-with-streamlit encontra os docs."""
    skill_file = (
        Path(__file__).parent.parent
        / ".agents"
        / "skills"
        / "developing-with-streamlit"
        / "SKILL.md"
    )
    assert skill_file.exists()
    discover_script = (
        Path(__file__).parent.parent
        / ".agents"
        / "skills"
        / "developing-with-streamlit"
        / "scripts"
        / "discover.py"
    )
    assert discover_script.exists()


def test_review_message_edited_text(app_config, tmp_path: Path) -> None:
    """Valida que review_message persiste edição manual do texto com status EDITED."""
    isolated_cfg = replace(
        app_config,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
    )
    storage = JsonStorage(isolated_cfg)
    storage.upsert_recruiter(
        Recruiter(
            id="rec-web-01",
            name="Recrutadora Exemplo",
            linkedin_url="https://www.linkedin.com/in/rec-exemplo",
            current_title="Tech Recruiter",
            location="Porto Alegre, RS",
        )
    )
    storage.upsert_message(
        SuggestedMessage(
            id="msg-edit-01",
            recruiter_id="rec-web-01",
            context="Contato inicial para vaga de Engenharia de Dados",
            message_text="Texto original do rascunho para revisão.",
            created_at="2026-11-11T10:00:00",
        )
    )

    updated = review_message(
        isolated_cfg,
        "msg-edit-01",
        edited_text="Texto ajustado manualmente antes do envio.",
    )
    assert updated.message_text == "Texto ajustado manualmente antes do envio."
    assert updated.review_status == ReviewStatus.EDITED

    reloaded = storage.get_message("msg-edit-01")
    assert reloaded is not None
    assert reloaded.message_text == "Texto ajustado manualmente antes do envio."
    assert reloaded.review_status == ReviewStatus.EDITED


def test_web_tabs_render_without_errors(app_config, tmp_path: Path) -> None:
    """Renderiza todas as abas do Streamlit com dados reais sem AttributeError ou exceções."""
    from streamlit.testing.v1 import AppTest

    isolated_cfg = replace(
        app_config,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        user_data_dir=tmp_path / "user_data",
        llm_provider="offline",
    )
    isolated_cfg.output_dir.mkdir(parents=True, exist_ok=True)
    isolated_cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    (isolated_cfg.output_dir / "relatorio_consolidado.md").write_text(
        "# Relatório Consolidado\n\nConteúdo de teste.",
        encoding="utf-8",
    )
    (isolated_cfg.logs_dir / "web_server.log").write_text(
        "Uvicorn server started on localhost:8501\n",
        encoding="utf-8",
    )
    (isolated_cfg.logs_dir / "linkedin_researcher.log").write_text(
        "INFO Inicializado\n",
        encoding="utf-8",
    )

    storage = JsonStorage(isolated_cfg)
    storage.upsert_recruiter(
        Recruiter(
            id="rec-01",
            name="Ana Recrutadora",
            linkedin_url="https://www.linkedin.com/in/ana-recrutadora",
            current_title="Especialista em Atração de Talentos",
            current_company="Empresa Alpha",
            location="São Paulo, SP",
        )
    )
    storage.upsert_company(
        Company(
            id="comp-01",
            name="Empresa Alpha",
            linkedin_url="https://www.linkedin.com/company/empresa-alpha",
            industry="Tecnologia",
            location="São Paulo, SP",
            source_urls=["https://www.linkedin.com/company/empresa-alpha"],
        )
    )
    storage.upsert_job(
        Job(
            id="job-high-01",
            title="Engenheiro de Dados Sênior",
            company="Empresa Alpha",
            location="Remoto",
            work_model="Remoto",
            application_url="https://www.linkedin.com/jobs/view/1001",
            checked_at="2026-11-11T10:00:00",
            match_score=89.0,
            match_level=MatchLevel.HIGH,
            strengths=["Python", "PySpark"],
            gaps=["GCP"],
        )
    )
    storage.upsert_job(
        Job(
            id="job-discarded-02",
            title="Desenvolvedor Frontend",
            company="Empresa Alpha",
            location="Híbrido",
            application_url="https://www.linkedin.com/jobs/view/1002",
            checked_at="2026-11-11T10:00:00",
            match_level=MatchLevel.NOT_EVALUATED,
            status=JobStatus.DISCARDED,
        )
    )
    storage.upsert_message(
        SuggestedMessage(
            id="msg-01",
            recruiter_id="rec-01",
            context="Vaga de Engenheiro de Dados Sênior",
            message_text=(
                "Olá Ana, tudo bem? Gostaria de me apresentar para oportunidades em Dados."
            ),
            created_at="2026-11-11T10:05:00",
        )
    )

    app_path = (
        Path(__file__).parent.parent
        / "src"
        / "linkedin_researcher"
        / "web"
        / "app.py"
    )
    with patch("linkedin_researcher.config.load_config", return_value=isolated_cfg):
        at = AppTest.from_file(str(app_path))
        at.run(timeout=15)
        assert not at.exception, f"Exceção na carga inicial: {at.exception}"

        pages = list(at.sidebar.radio[0].options)
        assert len(pages) == 7
        for page_name in pages:
            at.sidebar.radio[0].set_value(page_name)
            at.run(timeout=15)
            assert not at.exception, f"Exceção na aba '{page_name}': {at.exception}"

