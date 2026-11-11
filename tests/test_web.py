"""Testes unitários da interface web Streamlit."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

from linkedin_researcher.cli import build_parser, run_web


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


def test_run_web_command_invokes_streamlit(tmp_path: Path) -> None:
    """Valida se o comando run_web invoca o subprocesso do Streamlit com os parâmetros corretos."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        code = run_web(port=9000, host="127.0.0.1", headless=True)
        assert code == 0
        assert mock_run.called
        cmd_args = mock_run.call_args[0][0]
        assert "-m" in cmd_args
        assert "streamlit" in cmd_args
        assert "run" in cmd_args
        assert "--server.port" in cmd_args
        assert "9000" in cmd_args
        assert "--server.address" in cmd_args
        assert "127.0.0.1" in cmd_args
        assert "--server.headless" in cmd_args

