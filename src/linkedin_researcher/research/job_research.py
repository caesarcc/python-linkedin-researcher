"""Orquestração de pesquisa, descoberta e coleta de vagas no LinkedIn — Etapa 5."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.browser.linkedin_pages import (
    JobPageData,
    _clean_company_name,
    _now_iso,
    _strip_accents,
    extract_job_page,
    search_jobs_on_linkedin,
)
from linkedin_researcher.browser.session_manager import ensure_authenticated
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Company, Job, JobStatus, MatchLevel
from linkedin_researcher.storage import JsonStorage

logger = logging.getLogger("linkedin_researcher.research.jobs")


def _slugify(text: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", _strip_accents(text).casefold()).strip("-")
    return clean or "vaga"


def generate_job_id(company: str, title: str, source_url: str | None = None) -> str:
    """Gera ID previsível e legível para a vaga a partir do código numérico ou título."""
    if source_url:
        num_m = re.search(r"/jobs/view/(\d+)", source_url)
        if num_m:
            return f"job-{num_m.group(1)}"
    c_slug = _slugify(company)[:18].rstrip("-")
    t_slug = _slugify(title)[:24].rstrip("-")
    return f"job-{c_slug}-{t_slug}"


def write_jobs_markdown_report(jobs: list[Job], output_dir: Path) -> Path:
    """Gera relatório legível em output/oportunidades/resumo_vagas.md."""
    report_dir = output_dir / "oportunidades"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "resumo_vagas.md"

    lines = [
        "# Relatório de Oportunidades e Vagas Identificadas",
        "",
        (
            "| ID | Título da Vaga | Empresa | Localização | "
            "Modalidade | Contratação | Aderência | Consulta em |"
        ),
        "| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |",
    ]
    for j in jobs:
        match_str = j.match_level.value if j.match_level else "Não avaliada"
        lines.append(
            f"| `{j.id}` | **[{j.title}]({j.application_url})** | {j.company} | "
            f"{j.location} | {j.work_model} | {j.contract_type} | {match_str} | "
            f"{j.checked_at[:10]} |"
        )

    lines.extend(["", "## Detalhes Estruturados das Vagas", ""])
    for j in jobs:
        lines.extend(
            [
                f"### {j.title} — {j.company} (`{j.id}`)",
                f"- **Empresa:** {j.company}",
                f"- **Localização:** {j.location}",
                f"- **Modalidade:** {j.work_model}",
                f"- **Tipo de contratação:** {j.contract_type}",
                f"- **Salário:** {j.salary_range}",
                f"- **Data de publicação informada:** {j.published_at or 'Não informada'}",
                f"- **Data da consulta:** {j.checked_at}",
                f"- **URL de aplicação/consulta:** {j.application_url}",
                f"- **Status:** {j.status.value}",
            ]
        )
        if j.responsibilities:
            lines.append("- **Atividades e responsabilidades identificadas:**")
            for resp in j.responsibilities[:6]:
                lines.append(f"  - {resp}")
        if j.requirements:
            lines.append("- **Requisitos identificados:**")
            for req in j.requirements[:6]:
                lines.append(f"  - {req}")
        if j.strengths:
            lines.append("- **Pontos fortes com o currículo:**")
            for s in j.strengths:
                lines.append(f"  - {s}")
        if j.gaps:
            lines.append("- **Pontos a confirmar ou lacunas:**")
            for g in j.gaps:
                lines.append(f"  - {g}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def job_from_page_data(data: JobPageData, custom_id: str | None = None) -> Job:
    """Converte JobPageData extraído da página no modelo Pydantic Job validado."""
    job_id = custom_id or generate_job_id(data.company, data.title, data.source_url)
    return Job(
        id=job_id,
        title=data.title or "Vaga sem título",
        company=data.company or "Empresa confidencial",
        location=data.location,
        work_model=data.work_model,
        contract_type=data.contract_type,
        salary_range=data.salary_range,
        description=data.description,
        requirements=data.requirements,
        responsibilities=data.responsibilities,
        application_url=data.source_url,
        published_at=data.published_at,
        checked_at=data.checked_at,
        match_level=MatchLevel.NOT_EVALUATED,
        status=JobStatus.IDENTIFIED,
        source_urls=[data.source_url],
    )


async def research_single_job_on_page(
    page: Page,
    storage: JsonStorage,
    job_url: str,
    custom_id: str | None = None,
) -> Job:
    """Carrega a página da vaga, extrai seus dados e persiste no JsonStorage."""
    data = await extract_job_page(page, job_url=job_url, navigate=True)
    job = job_from_page_data(data, custom_id=custom_id)
    saved = storage.upsert_job(job)

    # Se a empresa for conhecida e não constar em empresas.json, registra placeholder
    if saved.company and saved.company.casefold() not in {
        "empresa confidencial",
        "a confirmar",
    }:
        c_id = f"comp-{_slugify(saved.company)}"
        if storage.get_company(c_id) is None:
            new_comp = Company(
                id=c_id,
                name=saved.company,
                location=saved.location,
                work_model=saved.work_model,
                source_urls=[saved.application_url],
            )
            storage.upsert_company(new_comp)

    return saved


async def research_jobs(
    config: AppConfig,
    keywords: str = "Assistente Administrativo",
    location: str = "Porto Alegre, RS",
    remote_only: bool = False,
    limit: int = 5,
) -> list[Job]:
    """Busca vagas no LinkedIn, visita suas páginas e registra em data/vagas.json."""
    storage = JsonStorage(config)
    results: list[Job] = []

    async with BrowserManager(config) as manager:
        page = await manager.get_page()
        await ensure_authenticated(page)

        print(f"\n[BUSCA] Pesquisando vagas: '{keywords}' em '{location}' (limite={limit})...")
        card_items = await search_jobs_on_linkedin(
            page,
            keywords=keywords,
            location=location,
            remote_only=remote_only,
            limit=limit,
        )

        if not card_items:
            print("[AVISO] Nenhuma vaga retornada na busca do LinkedIn para os termos informados.")
            return []

        print(f"[OK] {len(card_items)} vagas identificadas na busca. Coletando detalhes...")
        for idx, item in enumerate(card_items):
            if idx > 0:
                await manager.respectful_delay("intervalo entre páginas de vagas")

            print(
                f"\n[{idx + 1}/{len(card_items)}] Coletando vaga: "
                f"{item.title} ({item.company})..."
            )
            try:
                job = await research_single_job_on_page(
                    page, storage, job_url=item.job_url, custom_id=item.job_id
                )
                print(
                    f"  -> Localidade: {job.location}\n"
                    f"  -> Modalidade: {job.work_model} | Contratação: {job.contract_type}\n"
                    f"  -> Requisitos identificados: {len(job.requirements)}"
                )
                results.append(job)
            except PlaywrightError as exc:
                logger.error("Erro ao coletar vaga %s: %s", item.job_url, exc)
                await manager.capture_diagnostic_screenshot(page, prefix=f"err_{item.job_id}")

    all_jobs = storage.list_jobs()
    report_path = write_jobs_markdown_report(all_jobs, config.output_dir)
    print(f"\n[OK] Relatório de oportunidades salvo em: {report_path}")
    return results


async def register_job_by_url(
    config: AppConfig,
    job_url: str,
    custom_id: str | None = None,
) -> Job:
    """Acessa uma URL específica de vaga do LinkedIn, extrai seus dados e persiste."""
    storage = JsonStorage(config)
    async with BrowserManager(config) as manager:
        page = await manager.get_page()
        await ensure_authenticated(page)
        job = await research_single_job_on_page(page, storage, job_url=job_url, custom_id=custom_id)

    write_jobs_markdown_report(storage.list_jobs(), config.output_dir)
    return job


def register_job_manually(
    config: AppConfig,
    title: str,
    company: str,
    application_url: str,
    location: str = "a confirmar",
    work_model: str = "a confirmar",
    contract_type: str = "a confirmar",
    salary_range: str = "Não informado",
    description: str = "",
    requirements: list[str] | None = None,
    responsibilities: list[str] | None = None,
) -> Job:
    """Registra manualmente uma vaga sem requisição de rede e atualiza o relatório."""
    storage = JsonStorage(config)
    job_id = generate_job_id(company, title, application_url)
    now_str = _now_iso()

    job = Job(
        id=job_id,
        title=title.strip(),
        company=_clean_company_name(company.strip()),
        location=location.strip(),
        work_model=work_model.strip(),
        contract_type=contract_type.strip(),
        salary_range=salary_range.strip(),
        description=description.strip(),
        requirements=requirements or [],
        responsibilities=responsibilities or [],
        application_url=application_url.strip(),
        checked_at=now_str,
        source_urls=[application_url.strip()],
    )
    saved = storage.upsert_job(job)
    write_jobs_markdown_report(storage.list_jobs(), config.output_dir)
    return saved
