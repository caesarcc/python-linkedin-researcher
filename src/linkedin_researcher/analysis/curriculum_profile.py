"""Perfil estruturado do currículo e preferências profissionais configuráveis do candidato.

Fonte de dados:
- Arquivo de configuração de perfil: `data/perfil_candidato.json` (ou template)
- Currículo em PDF dentro do diretório `curriculum/`
- Informações adicionais qualitativas: `data/<nome>.md`

Nenhuma experiência, habilidade, idioma ou ferramenta não comprovada é inventada.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from pypdf import PdfReader

from linkedin_researcher.models import CandidateProfile, ExperienceEntry, Recruiter

if TYPE_CHECKING:
    from linkedin_researcher.config import AppConfig

logger = logging.getLogger("linkedin_researcher.analysis.curriculum")


def _slugify(text: str) -> str:
    """Gera slug legível em minúsculas sem acentuação."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("ASCII")
    clean = re.sub(r"[^\w\s-]", "", ascii_text.lower()).strip()
    return re.sub(r"[-\s]+", "-", clean)


def extract_curriculum_pdf_text(pdf_path: Path) -> str:
    """Extrai e normaliza o texto do currículo em PDF para conferência e validação local."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"Arquivo de currículo não encontrado em: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    pages_text = [(page.extract_text() or "") for page in reader.pages]
    raw_text = "\n".join(pages_text)
    return re.sub(r"\s+", " ", raw_text).strip()


def get_default_candidate_profile() -> CandidateProfile:
    """Perfil padrão genérico estruturado para fallback, desenvolvimento e testes locais."""
    return CandidateProfile(
        full_name="Candidato Modelo",
        location="São Paulo, SP",
        linkedin_url="https://www.linkedin.com/in/candidato-modelo",
        education="Bacharelado em Administração — Concluído",
        contract_availability=["CLT", "PJ"],
        has_active_mei=False,
        preferred_work_model="Prioritariamente Remoto, aceita Híbrido",
        priority_areas=[
            "Administrativa",
            "Financeira",
            "Comercial",
            "Faturamento",
            "Atendimento",
            "Back Office e Operações Administrativas",
        ],
        target_levels=["Assistente", "Analista"],
        target_roles_primary=[
            "Assistente Administrativo",
            "Assistente Financeiro",
            "Assistente Administrativo Financeiro",
            "Assistente Comercial",
            "Assistente de Faturamento",
            "Assistente de Atendimento",
        ],
        target_roles_expanded=[
            "Analista Administrativo",
            "Analista Administrativo Financeiro",
            "Analista de Faturamento",
            "Analista Comercial",
            "Assistente de Operações",
            "Assistente de Back Office",
            "Assistente de Cadastro",
            "Assistente de Contas a Pagar",
            "Assistente de Contas a Receber",
        ],
        excluded_roles_and_levels=[
            "Gerente",
            "Gestor",
            "Coordenador",
            "Coordenador de Faturamento",
            "Supervisor",
            "Diretor",
            "Chefe",
            "Líder de Equipe",
        ],
        proven_competencies=[
            "rotinas administrativas",
            "faturamento",
            "emissão e conferência de notas fiscais",
            "relatórios operacionais e financeiros",
            "controles financeiros",
            "fechamento de caixa",
            "cobrança",
            "atendimento ao cliente",
            "organização documental e contábil",
        ],
        behavioral_competencies=[
            "organização",
            "pontualidade",
            "atenção a detalhes",
            "comunicação interpessoal",
            "postura ética e responsável",
            "trabalho em equipe",
        ],
        office_proficiency="Pacote Office intermediário (Word, Excel, Outlook)",
        experiences=[
            ExperienceEntry(
                company="Empresa Modelo LTDA",
                period_pdf="01/2020 – Atual",
                role_in_pdf="Assistente Administrativo Financeiro",
                positioning_role="Assistente Administrativo Financeiro",
                is_current=True,
                activities=[
                    "Emissão e conferência de notas fiscais.",
                    "Controle de relatórios operacionais e financeiros.",
                    "Atendimento ao cliente e suporte operacional.",
                ],
            )
        ],
        pending_confirmations=[
            "Confirmar faixa salarial desejada — a confirmar",
        ],
    )


def load_candidate_additional_info(config: AppConfig | None = None) -> str | None:
    """Carrega o texto de diretrizes e informações qualitativas adicionais (se existir)."""
    if config is not None:
        if config.candidate_additional_info_file.exists():
            try:
                return config.candidate_additional_info_file.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning(
                    "Falha ao ler informações adicionais em %s: %s",
                    config.candidate_additional_info_file,
                    exc,
                )
    else:
        curriculum_dir = Path("curriculum")
        data_dir = Path("data")
        if curriculum_dir.exists():
            pdfs = sorted(curriculum_dir.glob("*.pdf"))
            if pdfs:
                matching_md = data_dir / f"{pdfs[0].stem}.md"
                if matching_md.exists():
                    try:
                        return matching_md.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
        default_path = data_dir / "informacoes_adicionais.md"
        if default_path.exists():
            try:
                return default_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return None


def parse_recruiters_from_markdown(md_text: str) -> list[Recruiter]:
    """Extrai lista de recrutadores a partir de tabelas ou listas em Markdown."""
    recruiters: list[Recruiter] = []
    if not md_text:
        return recruiters

    lines = md_text.splitlines()
    in_recruiter_section = False
    counter = 1

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#") and "recrutador" in line.lower():
            in_recruiter_section = True
            continue
        elif line.startswith("#") and in_recruiter_section:
            in_recruiter_section = False

        if not in_recruiter_section:
            continue

        # Formato 1: Tabela Markdown (| Nome | Cargo | Local | Empresa | Foco |)
        if line.startswith("|") and line.endswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if not parts:
                continue
            first = parts[0].lower()
            if first in {"nome", "recrutador", "name"} or set(parts[0]) <= {"-", ":", " "}:
                continue
            name = parts[0]
            current_title = parts[1] if len(parts) > 1 and parts[1] else "Recrutamento e Seleção"
            location = parts[2] if len(parts) > 2 and parts[2] else "Brasil"
            current_company = parts[3] if len(parts) > 3 and parts[3] else "Pendente"
            recruitment_focus = (
                [f.strip() for f in parts[4].split(",") if f.strip()]
                if len(parts) > 4 and parts[4]
                else ["Recrutamento e Seleção"]
            )
            slug = _slugify(name)
            rec_id = f"rec-{counter:02d}-{slug}"
            recruiters.append(
                Recruiter(
                    id=rec_id,
                    name=name,
                    current_title=current_title,
                    current_company=current_company,
                    location=location,
                    recruitment_focus=recruitment_focus,
                    company_verified=False,
                    professional_context="a confirmar",
                )
            )
            counter += 1
            continue

        # Formato 2: Lista com marcadores (- **Nome**: Cargo | Local | Empresa)
        list_match = re.match(r"^[-*]\s+\*\*([^*]+)\*\*:\s*(.+)$", line)
        if list_match:
            name = list_match.group(1).strip()
            rest = list_match.group(2).strip()
            segments = [s.strip() for s in rest.split("|")]
            current_title = (
                segments[0] if len(segments) > 0 and segments[0] else "Recrutamento e Seleção"
            )
            location = segments[1] if len(segments) > 1 and segments[1] else "Brasil"
            current_company = segments[2] if len(segments) > 2 and segments[2] else "Pendente"
            recruitment_focus = (
                [f.strip() for f in segments[3].split(",") if f.strip()]
                if len(segments) > 3 and segments[3]
                else ["Recrutamento e Seleção"]
            )
            slug = _slugify(name)
            rec_id = f"rec-{counter:02d}-{slug}"
            recruiters.append(
                Recruiter(
                    id=rec_id,
                    name=name,
                    current_title=current_title,
                    current_company=current_company,
                    location=location,
                    recruitment_focus=recruitment_focus,
                    company_verified=False,
                    professional_context="a confirmar",
                )
            )
            counter += 1

    return recruiters


def load_candidate_profile(config: AppConfig | None = None) -> CandidateProfile:
    """Carrega o perfil do candidato a partir de perfil_candidato.json ou fallback."""
    profile: CandidateProfile | None = None

    if config is not None:
        if config.candidate_profile_file.exists():
            try:
                content = config.candidate_profile_file.read_text(encoding="utf-8")
                profile = CandidateProfile.model_validate_json(content)
            except Exception as exc:
                logger.warning(
                    "Falha ao ler perfil do candidato em %s: %s. Tentando template ou padrão.",
                    config.candidate_profile_file,
                    exc,
                )
        if profile is None and config.candidate_profile_template_file.exists():
            try:
                content = config.candidate_profile_template_file.read_text(encoding="utf-8")
                profile = CandidateProfile.model_validate_json(content)
            except Exception:
                pass
    else:
        default_json = Path("data/perfil_candidato.json")
        if default_json.exists():
            try:
                content = default_json.read_text(encoding="utf-8")
                profile = CandidateProfile.model_validate_json(content)
            except Exception:
                pass

    if profile is None:
        profile = get_default_candidate_profile()

    add_info = load_candidate_additional_info(config)
    if add_info:
        profile.additional_info = add_info

    return profile


def save_candidate_profile(profile: CandidateProfile, path: Path) -> Path:
    """Salva o perfil de candidato em formato JSON estruturado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_data = profile.model_dump(mode="json", exclude={"additional_info"})
    path.write_text(json.dumps(dump_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_profile_and_recruiters_from_cv_and_md(
    pdf_path: Path,
    md_path: Path | None = None,
    config: AppConfig | None = None,
) -> tuple[CandidateProfile, list[Recruiter]]:
    """Gera arquivos JSON a partir do currículo (.pdf) e do arquivo MD de informações."""
    from linkedin_researcher.config import load_config, validate_curriculum_pdf_extension
    from linkedin_researcher.storage import JsonStorage

    cfg = config or load_config()

    if not pdf_path.exists():
        raise FileNotFoundError(f"Arquivo de currículo não encontrado: {pdf_path}")

    # Rejeita estritamente arquivos Word (.docx)
    validate_curriculum_pdf_extension(pdf_path)

    # 1. Leitura do arquivo MD complementar (com mesmo nome do currículo na pasta data/)
    md_content = ""
    target_md = md_path
    if target_md is None:
        expected_md = cfg.data_dir / f"{pdf_path.stem}.md"
        if expected_md.exists():
            target_md = expected_md
        elif cfg.candidate_additional_info_file.exists():
            target_md = cfg.candidate_additional_info_file

    if target_md and target_md.exists():
        md_content = target_md.read_text(encoding="utf-8").strip()

    # 2. Carrega ou atualiza o perfil do candidato ativo
    profile = load_candidate_profile(cfg)
    if md_content:
        profile.additional_info = md_content

    save_candidate_profile(profile, cfg.candidate_profile_file)

    # 3. Extração e cadastro dos recrutadores a partir do MD
    recruiters = parse_recruiters_from_markdown(md_content)
    if recruiters:
        storage = JsonStorage(cfg)
        for rec in recruiters:
            storage.upsert_recruiter(rec)

    return profile, recruiters
