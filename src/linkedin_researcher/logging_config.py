"""Configuração de logging estruturado sem exposição de dados sensíveis."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(logs_dir: Path, level_name: str = "INFO") -> logging.Logger:
    """Configura logger raiz do pacote com saída em console e arquivo."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "linkedin_researcher.log"

    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger("linkedin_researcher")
    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
