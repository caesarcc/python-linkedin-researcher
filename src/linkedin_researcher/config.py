"""Configuração centralizada do projeto via variáveis de ambiente e pathlib."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Localiza a raiz do projeto a partir da estrutura de pacotes."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    """Configurações imutáveis da aplicação local (sem credenciais)."""

    project_root: Path
    user_data_dir: Path
    headless: bool
    default_timeout_ms: int
    navigation_timeout_ms: int
    min_action_delay_sec: float
    max_action_delay_sec: float
    data_dir: Path
    curriculum_path: Path
    candidate_profile_path: Path
    output_dir: Path
    logs_dir: Path
    log_level: str
    candidate_additional_info_path: Path = Path("data/informacoes_adicionais.md")
    browser_channel: str = "chrome"
    gemini_enabled: bool = True
    gemini_model: str = "gemini-3.8-flash"
    gemini_max_calls_per_run: int = 5
    has_gemini_api_key: bool = False

    @property
    def candidate_profile_file(self) -> Path:
        return self.candidate_profile_path

    @property
    def candidate_profile_template_file(self) -> Path:
        return self.data_dir / "perfil_candidato.template.json"

    @property
    def candidate_additional_info_file(self) -> Path:
        return self.candidate_additional_info_path

    @property
    def candidate_additional_info_template_file(self) -> Path:
        return self.data_dir / "informacoes_adicionais.template.md"

    @property
    def recruiters_file(self) -> Path:
        return self.data_dir / "recrutadores.json"

    @property
    def recruiters_template_file(self) -> Path:
        return self.data_dir / "recrutadores.template.json"

    @property
    def companies_file(self) -> Path:
        return self.data_dir / "empresas.json"

    @property
    def companies_template_file(self) -> Path:
        return self.data_dir / "empresas.template.json"

    @property
    def jobs_file(self) -> Path:
        return self.data_dir / "vagas.json"

    @property
    def jobs_template_file(self) -> Path:
        return self.data_dir / "vagas.template.json"

    @property
    def contacts_file(self) -> Path:
        return self.data_dir / "contatos.json"

    @property
    def contacts_template_file(self) -> Path:
        return self.data_dir / "contatos.template.json"

    @property
    def playwright_profile_dir(self) -> Path:
        """Alias para user_data_dir (diretório de perfil persistente do Playwright)."""
        return self.user_data_dir

    @property
    def curriculum_pdf_path(self) -> Path:
        """Alias para curriculum_path."""
        return self.curriculum_path

    @property
    def additional_info_path(self) -> Path:
        """Alias para candidate_additional_info_path."""
        return self.candidate_additional_info_path


def validate_curriculum_pdf_extension(path: Path) -> None:
    """Valida se o currículo é estritamente .pdf, rejeitando explicitamente .docx e outros."""
    suffix = path.suffix.lower()
    if suffix in {".docx", ".doc"}:
        raise ValueError(
            f"Arquivo '{path.name}' inválido. Arquivos Word (.docx/.doc) não são permitidos. "
            "O sistema aceita exclusivamente currículos em formato .pdf."
        )
    if suffix != ".pdf":
        raise ValueError(
            f"Arquivo '{path.name}' inválido. "
            "O sistema aceita exclusivamente currículos no formato .pdf."
        )


def _detect_default_curriculum_path(root: Path) -> Path:
    """Detecta automaticamente o arquivo de currículo (.pdf) dentro de curriculum/."""
    curriculum_dir = root / "curriculum"
    if curriculum_dir.exists():
        docx_files = list(curriculum_dir.glob("*.docx")) + list(curriculum_dir.glob("*.doc"))
        if docx_files:
            raise ValueError(
                f"Arquivo Word proibido encontrado em curriculum/: '{docx_files[0].name}'. "
                "O sistema aceita exclusivamente currículos em formato .pdf."
            )
        pdfs = sorted(curriculum_dir.glob("*.pdf"))
        if pdfs:
            return pdfs[0]
    return curriculum_dir / "curriculo.pdf"


def load_config(project_root: Path | None = None) -> AppConfig:
    """Carrega variáveis do arquivo .env (se existir) e retorna AppConfig validado."""
    root = project_root or _find_project_root()
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

    def _resolve_path(env_key: str, default_path: Path) -> Path:
        raw = os.getenv(env_key, "").strip()
        if not raw:
            return default_path
        p = Path(raw)
        return p if p.is_absolute() else (root / p)

    headless_raw = os.getenv("LINKEDIN_HEADLESS", "false").strip().lower()
    headless = headless_raw in {"1", "true", "yes", "on"}

    gemini_enabled_raw = os.getenv("GEMINI_ENABLED", "true").strip().lower()
    gemini_enabled = gemini_enabled_raw in {"1", "true", "yes", "on"}
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

    data_dir = _resolve_path("LINKEDIN_DATA_DIR", root / "data")
    default_cv = _detect_default_curriculum_path(root)
    curriculum_path = _resolve_path("LINKEDIN_CURRICULUM_PATH", default_cv)
    if curriculum_path.exists():
        validate_curriculum_pdf_extension(curriculum_path)

    # Associa arquivo MD com o mesmo nome do currículo na pasta data/ (se existir)
    cv_stem = curriculum_path.stem
    matching_md = data_dir / f"{cv_stem}.md"
    default_add_info = (
        matching_md if matching_md.exists() else (data_dir / "informacoes_adicionais.md")
    )
    candidate_additional_info_path = _resolve_path(
        "LINKEDIN_ADDITIONAL_INFO_PATH", default_add_info
    )

    return AppConfig(
        project_root=root,
        user_data_dir=_resolve_path("LINKEDIN_USER_DATA_DIR", root / ".playwright-profile"),
        headless=headless,
        default_timeout_ms=int(os.getenv("LINKEDIN_DEFAULT_TIMEOUT_MS", "30000")),
        navigation_timeout_ms=int(os.getenv("LINKEDIN_NAVIGATION_TIMEOUT_MS", "45000")),
        min_action_delay_sec=float(os.getenv("LINKEDIN_MIN_ACTION_DELAY_SEC", "3.0")),
        max_action_delay_sec=float(os.getenv("LINKEDIN_MAX_ACTION_DELAY_SEC", "7.0")),
        data_dir=data_dir,
        curriculum_path=curriculum_path,
        candidate_profile_path=_resolve_path(
            "LINKEDIN_CANDIDATE_PROFILE_PATH", data_dir / "perfil_candidato.json"
        ),
        candidate_additional_info_path=candidate_additional_info_path,
        output_dir=_resolve_path("LINKEDIN_OUTPUT_DIR", root / "output"),
        logs_dir=_resolve_path("LINKEDIN_LOGS_DIR", root / "logs"),
        log_level=os.getenv("LINKEDIN_LOG_LEVEL", "INFO").strip().upper(),
        browser_channel=os.getenv("LINKEDIN_BROWSER_CHANNEL", "chrome").strip(),
        gemini_enabled=gemini_enabled,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash",
        gemini_max_calls_per_run=max(1, int(os.getenv("GEMINI_MAX_CALLS_PER_RUN", "5"))),
        has_gemini_api_key=bool(gemini_api_key),
    )
