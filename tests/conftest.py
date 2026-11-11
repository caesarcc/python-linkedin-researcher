"""Fixtures compartilhadas para os testes automatizados."""

from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_researcher.config import AppConfig, load_config


@pytest.fixture
def app_config() -> AppConfig:
    """Retorna a configuração padrão carregada a partir da raiz do projeto."""
    return load_config()


@pytest.fixture
def project_root(app_config: AppConfig) -> Path:
    """Retorna o caminho raiz do projeto."""
    return app_config.project_root
