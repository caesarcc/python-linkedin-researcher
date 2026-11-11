"""Orquestração de pesquisa e confirmação de recrutadores e suas empresas — Etapa 3 e 4."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.browser.linkedin_pages import (
    ProfilePageData,
    _now_iso,
    _strip_accents,
    extract_recruiter_profile_page,
    search_recruiter_on_linkedin,
)
from linkedin_researcher.browser.session_manager import (
    ManualInterventionRequiredError,
    ensure_authenticated,
)
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Company, Recruiter
from linkedin_researcher.storage import JsonStorage

logger = logging.getLogger("linkedin_researcher.research.recruiters")


def _slugify(text: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", _strip_accents(text).casefold()).strip("-")
    return clean or "empresa"


def _infer_recruitment_focus(headline: str, about_text: str, existing: list[str]) -> list[str]:
    """Identifica áreas e modalidade de atuação em R&S com base no texto observado."""
    combined = f"{headline} {about_text}".casefold()
    focus = list(existing)

    mapping = [
        ("hunting", "Hunting"),
        ("headhunter", "Headhunting"),
        ("consultoria", "Consultoria de RH"),
        ("talent acquisition", "Talent Acquisition"),
        ("recrutamento e seleção", "Recrutamento e Seleção"),
        ("r&s", "Recrutamento e Seleção"),
        ("administrativ", "Vagas Administrativas/Corporativas"),
        ("financeir", "Vagas Financeiras"),
        ("comercial", "Vagas Comerciais"),
        ("operacion", "Vagas Operacionais"),
        ("tech", "Tech Recruiting"),
    ]
    for keyword, label in mapping:
        if keyword in combined and label not in focus:
            focus.append(label)
    return focus


def _build_professional_context(profile: ProfilePageData, fallback: str) -> str:
    parts: list[str] = []
    if profile.current_role_title and profile.current_company:
        status_str = (
            "confirmado na seção Experiência" if profile.company_verified else "a confirmar"
        )
        parts.append(
            f"Cargo atual observado: {profile.current_role_title} "
            f"em {profile.current_company} ({status_str})."
        )
    elif profile.current_company:
        parts.append(f"Empresa associada: {profile.current_company}.")

    if profile.about_text:
        short_about = profile.about_text[:280].rstrip()
        if len(profile.about_text) > 280:
            short_about += "..."
        parts.append(f"Resumo 'Sobre': {short_about}")

    if not parts:
        return fallback
    return " ".join(parts)


def apply_profile_data_to_recruiter(
    recruiter: Recruiter,
    profile: ProfilePageData,
    search_company_hint: str | None = None,
) -> Recruiter:
    """Mescla os dados extraídos da página no modelo Recruiter de forma segura e auditável."""
    new_company = recruiter.current_company
    company_verified = recruiter.company_verified

    if profile.current_company:
        new_company = profile.current_company
        company_verified = profile.company_verified
    elif search_company_hint:
        new_company = f"{search_company_hint} (exibida na busca; confirmar no perfil)"
        company_verified = False

    new_title = profile.headline if profile.headline else recruiter.current_title
    new_location = profile.location if profile.location else recruiter.location
    new_focus = _infer_recruitment_focus(new_title, profile.about_text, recruiter.recruitment_focus)
    new_context = _build_professional_context(profile, recruiter.professional_context)
    notes_joined = (
        "; ".join(profile.extraction_notes) if profile.extraction_notes else recruiter.notes
    )

    return recruiter.model_copy(
        update={
            "linkedin_url": profile.source_url,
            "source_url": profile.source_url,
            "profile_checked_at": profile.checked_at,
            "current_title": new_title,
            "location": new_location,
            "current_company": new_company,
            "company_verified": company_verified,
            "recruitment_focus": new_focus,
            "professional_context": new_context,
            "notes": notes_joined,
        }
    )


def register_company_from_profile(
    storage: JsonStorage,
    profile: ProfilePageData,
) -> Company | None:
    """Se o perfil revelou uma empresa válida, registra ou atualiza em data/empresas.json."""
    if not profile.current_company:
        return None
    clean_name = re.sub(r"\s*\(.*?\)\s*$", "", profile.current_company).strip()
    if not clean_name or clean_name.casefold() in {"pendente", "a confirmar"}:
        return None

    comp_id = f"comp-{_slugify(clean_name)}"
    sources = [profile.source_url]
    if profile.company_linkedin_url and profile.company_linkedin_url not in sources:
        sources.append(profile.company_linkedin_url)

    company = Company(
        id=comp_id,
        name=clean_name,
        linkedin_url=profile.company_linkedin_url,
        location=profile.location or "a confirmar",
        verified_at=profile.checked_at if profile.company_verified else None,
        source_urls=sources,
    )
    return storage.upsert_company(company)


def write_recruiters_markdown_report(recruiters: list[Recruiter], output_dir: Path) -> Path:
    """Gera relatório Markdown legível em output/recrutadores/resumo_recrutadores.md."""
    report_dir = output_dir / "recrutadores"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "resumo_recrutadores.md"

    lines = [
        "# Relatório Consolidado de Recrutadores e Empresas",
        "",
        (
            "| ID | Nome | Empresa Atual | Vínculo Confirmado? | "
            "Local | URL do Perfil | Última Verificação |"
        ),
        "| :--- | :--- | :--- | :---: | :--- | :--- | :--- |",
    ]
    for r in recruiters:
        ver_str = "Sim" if r.company_verified else "Pendente"
        url_str = r.linkedin_url or "Não localizado"
        checked_str = r.profile_checked_at or "-"
        lines.append(
            f"| `{r.id}` | **{r.name}** | {r.current_company} | {ver_str} | "
            f"{r.location} | {url_str} | {checked_str} |"
        )

    lines.extend(["", "## Contexto Profissional Detalhado", ""])
    for r in recruiters:
        lines.extend(
            [
                f"### {r.name} (`{r.id}`)",
                f"- **Título exibido:** {r.current_title}",
                (
                    f"- **Empresa atual:** {r.current_company} "
                    f"(`company_verified={r.company_verified}`)"
                ),
                f"- **Localização:** {r.location}",
                f"- **Foco de recrutamento:** {', '.join(r.recruitment_focus) or 'a confirmar'}",
                f"- **Contexto observado:** {r.professional_context}",
                f"- **Fonte / URL:** {r.source_url or 'Pendente'}",
                f"- **Notas:** {r.notes}",
                "",
            ]
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


async def research_single_recruiter_on_page(
    page: Page,
    manager: BrowserManager,
    storage: JsonStorage,
    recruiter: Recruiter,
) -> Recruiter:
    """Executa a pesquisa de um recrutador usando uma página autenticada aberta."""
    target_url = recruiter.linkedin_url
    search_company_hint: str | None = None

    if not target_url:
        candidate = await search_recruiter_on_linkedin(
            page,
            name=recruiter.name,
            location_hint=recruiter.location,
            title_hint=recruiter.current_title,
        )
        if candidate is None:
            logger.warning("Perfil de '%s' não localizado na busca.", recruiter.name)
            updated_not_found = recruiter.model_copy(
                update={
                    "notes": (
                        "Busca executada, mas perfil não foi localizado univocamente. "
                        "Informe a URL manualmente se disponível."
                    )
                }
            )
            return storage.upsert_recruiter(updated_not_found)

        target_url = candidate.profile_url
        search_company_hint = candidate.current_company_hint
        await manager.respectful_delay("pausa entre busca e abertura do perfil")

    try:
        profile_data = await extract_recruiter_profile_page(
            page, profile_url=target_url, navigate=True
        )
    except ManualInterventionRequiredError:
        raise
    except PlaywrightError as exc:
        logger.error("Erro ao extrair perfil de %s (%s): %s", recruiter.name, target_url, exc)
        await manager.capture_diagnostic_screenshot(page, prefix=f"err_{recruiter.id}")
        return recruiter

    updated = apply_profile_data_to_recruiter(
        recruiter, profile_data, search_company_hint=search_company_hint
    )
    saved = storage.upsert_recruiter(updated)
    register_company_from_profile(storage, profile_data)
    return saved


async def research_recruiters(
    config: AppConfig,
    recruiter_id: str | None = None,
    research_all: bool = False,
) -> list[Recruiter]:
    """Pesquisa um recrutador específico (--id) ou todos os cadastrados (--all)."""
    storage = JsonStorage(config)
    storage.seed_initial_recruiters()

    if research_all or recruiter_id == "all":
        targets = storage.list_recruiters()
    else:
        if not recruiter_id:
            raise ValueError("Informe --id <id> ou --all para pesquisar recrutadores.")
        found = storage.get_recruiter(recruiter_id)
        if found is None:
            raise ValueError(
                f"Recrutador '{recruiter_id}' não encontrado. "
                "Use 'linkedin-researcher recruiters list' para ver os IDs."
            )
        targets = [found]

    results: list[Recruiter] = []
    async with BrowserManager(config) as manager:
        page = await manager.get_page()
        await ensure_authenticated(page)

        for idx, rec in enumerate(targets):
            if idx > 0:
                await manager.respectful_delay("intervalo entre perfis de recrutadores")
            print(f"\n[{idx + 1}/{len(targets)}] Pesquisando recrutador: {rec.name} ({rec.id})...")
            updated = await research_single_recruiter_on_page(page, manager, storage, rec)
            status = "Confirmada" if updated.company_verified else "A confirmar"
            print(
                f"  -> Empresa identificada: {updated.current_company} ({status})\n"
                f"  -> Perfil: {updated.linkedin_url or 'Não localizado'}"
            )
            results.append(updated)

    all_recruiters = storage.list_recruiters()
    report_path = write_recruiters_markdown_report(all_recruiters, config.output_dir)
    print(f"\n[OK] Relatório atualizado em: {report_path}")
    return results


def manually_update_recruiter(
    config: AppConfig,
    recruiter_id: str,
    company_name: str | None = None,
    verified: bool | None = None,
    linkedin_url: str | None = None,
    title: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Recruiter:
    """Atualiza ou confirma manualmente campos Pendentes de um recrutador e regenera o relatório."""
    storage = JsonStorage(config)
    storage.seed_initial_recruiters()
    rec = storage.get_recruiter(recruiter_id)
    if rec is None:
        raise ValueError(
            f"Recrutador '{recruiter_id}' não encontrado. "
            "Use 'linkedin-researcher recruiters list' para ver os IDs."
        )

    now_str = _now_iso()
    updates: dict[str, object] = {"profile_checked_at": now_str}
    if company_name is not None:
        updates["current_company"] = company_name.strip()
        if verified is None:
            updates["company_verified"] = True
    if verified is not None:
        updates["company_verified"] = verified
    if linkedin_url is not None:
        updates["linkedin_url"] = linkedin_url.strip()
        updates["source_url"] = linkedin_url.strip()
    if title is not None:
        updates["current_title"] = title.strip()
    if location is not None:
        updates["location"] = location.strip()
    if notes is not None:
        updates["notes"] = notes.strip()
    elif company_name is not None:
        updates["notes"] = f"Vínculo com '{company_name.strip()}' confirmado manualmente."

    updated = rec.model_copy(update=updates)
    saved = storage.upsert_recruiter(updated)

    if saved.current_company and saved.current_company.casefold() not in {
        "pendente",
        "a confirmar",
    }:
        fake_profile = ProfilePageData(
            source_url=saved.source_url or saved.linkedin_url or "confirmacao-manual",
            checked_at=now_str,
            current_company=saved.current_company,
            company_verified=saved.company_verified,
            location=saved.location,
        )
        register_company_from_profile(storage, fake_profile)

    write_recruiters_markdown_report(storage.list_recruiters(), config.output_dir)
    return saved
