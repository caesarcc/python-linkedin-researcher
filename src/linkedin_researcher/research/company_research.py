"""Pesquisa e verificação de páginas de empresas no LinkedIn — Etapa 4."""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.browser.linkedin_pages import (
    extract_company_page,
    search_company_on_linkedin,
)
from linkedin_researcher.browser.session_manager import ensure_authenticated
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Company
from linkedin_researcher.storage import JsonStorage

logger = logging.getLogger("linkedin_researcher.research.companies")


def write_companies_markdown_report(companies: list[Company], output_dir: Path) -> Path:
    """Gera relatório Markdown legível em output/recrutadores/resumo_empresas.md."""
    report_dir = output_dir / "recrutadores"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "resumo_empresas.md"

    lines = [
        "# Relatório Consolidado de Empresas Identificadas",
        "",
        (
            "| ID | Nome da Empresa | Setor | Sede | "
            "Website | LinkedIn | Verificado em |"
        ),
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for c in companies:
        site_str = f"[{c.website}]({c.website})" if c.website else "-"
        li_str = f"[LinkedIn]({c.linkedin_url})" if c.linkedin_url else "Pendente"
        lines.append(
            f"| `{c.id}` | **{c.name}** | {c.industry} | {c.location} | "
            f"{site_str} | {li_str} | {c.verified_at or '-'} |"
        )

    lines.extend(["", "## Descrição e Detalhes Institucionais", ""])
    for c in companies:
        lines.extend(
            [
                f"### {c.name} (`{c.id}`)",
                f"- **Setor:** {c.industry}",
                f"- **Localização/Sede:** {c.location}",
                f"- **Modelo de Trabalho:** {c.work_model}",
                f"- **Website:** {c.website or 'Não informado'}",
                f"- **LinkedIn:** {c.linkedin_url or 'Pendente'}",
                f"- **Última verificação:** {c.verified_at or 'Pendente'}",
                f"- **Descrição:** {c.company_description or 'Não coletada'}",
                "",
            ]
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


async def research_single_company_on_page(
    page: Page,
    manager: BrowserManager,
    storage: JsonStorage,
    company: Company,
) -> Company:
    """Pesquisa e atualiza uma empresa usando uma página autenticada aberta."""
    target_url = company.linkedin_url
    if not target_url:
        logger.info("Empresa '%s' sem URL direta; buscando no LinkedIn...", company.name)
        found_url = await search_company_on_linkedin(page, company.name)
        if not found_url:
            logger.warning("Página da empresa '%s' não localizada na busca.", company.name)
            return company
        target_url = found_url
        await manager.respectful_delay("pausa após busca da empresa")

    try:
        page_data = await extract_company_page(page, company_url=target_url, navigate=True)
    except PlaywrightError as exc:
        logger.error("Erro ao extrair página da empresa %s (%s): %s", company.name, target_url, exc)
        await manager.capture_diagnostic_screenshot(page, prefix=f"err_{company.id}")
        return company

    sources = list(company.source_urls)
    for src in (page_data.source_url, target_url):
        if src and src not in sources:
            sources.append(src)

    updated = company.model_copy(
        update={
            "name": page_data.name or company.name,
            "linkedin_url": target_url,
            "industry": page_data.industry,
            "location": page_data.location,
            "website": page_data.website or company.website,
            "company_description": page_data.description or company.company_description,
            "verified_at": page_data.checked_at,
            "source_urls": sources,
        }
    )
    return storage.upsert_company(updated)


async def research_companies(
    config: AppConfig,
    company_id: str | None = None,
    research_all: bool = False,
) -> list[Company]:
    """Pesquisa uma empresa específica (--id) ou todas as cadastradas (--all)."""
    storage = JsonStorage(config)
    all_stored = storage.list_companies()
    if not all_stored:
        print("[AVISO] Nenhuma empresa cadastrada em data/empresas.json ainda.")
        return []

    if research_all or company_id == "all":
        targets = all_stored
    else:
        if not company_id:
            raise ValueError("Informe --id <id> ou --all para pesquisar empresas.")
        found = storage.get_company(company_id)
        if found is None:
            raise ValueError(
                f"Empresa '{company_id}' não encontrada em data/empresas.json. "
                "Use 'linkedin-researcher companies list' para ver os IDs."
            )
        targets = [found]

    results: list[Company] = []
    async with BrowserManager(config) as manager:
        page = await manager.get_page()
        await ensure_authenticated(page)

        for idx, comp in enumerate(targets):
            if idx > 0:
                await manager.respectful_delay("intervalo entre páginas de empresas")
            print(f"\n[{idx + 1}/{len(targets)}] Pesquisando empresa: {comp.name} ({comp.id})...")
            updated = await research_single_company_on_page(page, manager, storage, comp)
            print(
                f"  -> Setor: {updated.industry}\n"
                f"  -> Sede: {updated.location}\n"
                f"  -> Site: {updated.website or 'Não informado'}"
            )
            results.append(updated)

    all_companies = storage.list_companies()
    report_path = write_companies_markdown_report(all_companies, config.output_dir)
    print(f"\n[OK] Relatório de empresas atualizado em: {report_path}")
    return results


async def research_company_by_id(config: AppConfig, company_id: str) -> Company:
    """Wrapper para compatibilidade retroativa."""
    res = await research_companies(config, company_id=company_id)
    if not res:
        raise RuntimeError(f"Não foi possível pesquisar empresa {company_id}.")
    return res[0]
