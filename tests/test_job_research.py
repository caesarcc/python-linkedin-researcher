"""Testes de descoberta, extração local e persistência de vagas — Etapa 5.

Nenhum teste acessa o LinkedIn real na internet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.browser.linkedin_pages import (
    _canonical_job_url,
    extract_job_page,
    search_jobs_on_linkedin,
)
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import JobStatus, MatchLevel
from linkedin_researcher.research.job_research import (
    generate_job_id,
    job_from_page_data,
    register_job_manually,
    write_jobs_markdown_report,
)
from linkedin_researcher.storage import JsonStorage

MOCK_JOB_VIEW_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Assistente Administrativo e Financeiro | LinkedIn</title></head>
<body>
  <nav id="global-nav"><a href="https://www.linkedin.com/feed/">Início</a></nav>
  <main>
    <div class="job-view-layout">
      <h1>Assistente Administrativo e Financeiro</h1>
      <div class="job-details-jobs-unified-top-card__company-name">
        <a href="https://www.linkedin.com/company/logistica-sul-exemplo/">Logística Sul Exemplo</a>
      </div>
      <div class="job-details-jobs-unified-top-card__primary-description-container">
        Canoas, Rio Grande do Sul, Brasil · Híbrido · há 3 dias
      </div>
      <div class="job-details-jobs-unified-top-card__job-insight">
        Tempo integral · CLT · R$ 2.800,00 a R$ 3.200,00
      </div>

      <article class="jobs-description__container">
        <h2>Sobre a vaga</h2>
        <p>Buscamos Assistente Administrativo e Financeiro para atuação em Canoas/RS.</p>

        <h3>Responsabilidades e atribuições:</h3>
        <ul>
          <li>Emissão e conferência de notas fiscais de entrada e saída.</li>
          <li>Controle de contas a pagar e a receber e fluxo de caixa.</li>
          <li>Acompanhamento de relatórios gerenciais e conciliação bancária.</li>
          <li>Atendimento a fornecedores e clientes e suporte à equipe comercial.</li>
        </ul>

        <h3>Requisitos e qualificações:</h3>
        <ul>
          <li>Ensino médio completo ou superior em andamento (Administração, Contabilidade).</li>
          <li>Experiência comprovada em rotinas administrativas e financeiras.</li>
          <li>Conhecimento intermediário do Pacote Office (Excel).</li>
          <li>Residir em Canoas, Porto Alegre ou região metropolitana.</li>
        </ul>
      </article>
    </div>
  </main>
</body>
</html>
"""

MOCK_JOB_SEARCH_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Vagas de Assistente Administrativo | LinkedIn</title></head>
<body>
  <nav id="global-nav"><a href="https://www.linkedin.com/feed/">Início</a></nav>
  <main>
    <ul class="scaffold-layout__list-container">
      <li class="jobs-search-results__list-item">
        <div class="job-card-container">
          <a class="job-card-list__title--link" href="https://www.linkedin.com/jobs/view/4123456789/?trackingId=abc">
            Assistente Administrativo
          </a>
          <div class="job-card-container__primary-description">Transportes Rápido Ltda</div>
          <div class="job-card-container__metadata-item">Porto Alegre, RS · Presencial</div>
        </div>
      </li>
      <li class="jobs-search-results__list-item">
        <div class="job-card-container">
          <a class="job-card-list__title--link" href="https://www.linkedin.com/jobs/view/4987654321/?trackingId=xyz">
            Analista Financeiro Júnior
          </a>
          <div class="job-card-container__primary-description">Grupo Sul Alimentos</div>
          <div class="job-card-container__metadata-item">Canoas, RS · Híbrido</div>
        </div>
      </li>
    </ul>
  </main>
</body>
</html>
"""


MOCK_JOB_SEARCH_MODERN_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Pesquisa de vagas | LinkedIn</title></head>
<body>
  <main>
    <div data-view-name="job-search-job-card">
      <div componentkey="job-card-component-ref-4485316942">
        <div>Selecionada, Assistente administrativo Pl - POA</div>
        <div>Assistente administrativo Pl - POA</div>
        <div>Konica Minolta Business Solutions do Brasil</div>
        <div>Porto Alegre e Região (Híbrido)</div>
        <div>Visto</div>
      </div>
    </div>
    <div data-view-name="job-search-job-card">
      <div componentkey="job-card-component-ref-4476681514">
        <div>ASSISTENTE ADMINISTRATIVO (Vaga verificada)</div>
        <div>ASSISTENTE ADMINISTRATIVO</div>
        <div>Coca-Cola FEMSA</div>
        <div>Porto Alegre, RS</div>
      </div>
    </div>
  </main>
</body>
</html>
"""


def _make_test_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        project_root=tmp_path,
        user_data_dir=tmp_path / ".playwright-profile",
        headless=True,
        default_timeout_ms=10_000,
        navigation_timeout_ms=15_000,
        min_action_delay_sec=0.05,
        max_action_delay_sec=0.1,
        data_dir=data_dir,
        curriculum_path=tmp_path / "curriculum" / "curriculo.pdf",
        candidate_profile_path=data_dir / "perfil_candidato.json",
        candidate_additional_info_path=data_dir / "informacoes_adicionais.md",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        log_level="INFO",
        browser_channel="chrome",
    )


def test_canonical_job_url_cleaning() -> None:
    raw = "https://www.linkedin.com/jobs/view/4123456789/?trackingId=abcdef&refId=123"
    cleaned = _canonical_job_url(raw)
    assert cleaned == "https://www.linkedin.com/jobs/view/4123456789/"

    param_url = "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4987654321"
    cleaned_param = _canonical_job_url(param_url)
    assert cleaned_param == "https://www.linkedin.com/jobs/view/4987654321/"

    assert _canonical_job_url("") is None


@pytest.mark.asyncio
async def test_extract_local_job_page(tmp_path: Path) -> None:
    cfg = _make_test_config(tmp_path)
    job_html_file = tmp_path / "mock_job.html"
    job_html_file.write_text(MOCK_JOB_VIEW_HTML, encoding="utf-8")

    async with BrowserManager(cfg) as manager:
        page = await manager.get_page()
        await page.goto(job_html_file.as_uri(), wait_until="domcontentloaded")

        job_data = await extract_job_page(page, job_url=job_html_file.as_uri(), navigate=False)
        assert job_data.title == "Assistente Administrativo e Financeiro"
        assert job_data.company == "Logística Sul Exemplo"
        assert "Canoas" in job_data.location
        assert job_data.work_model == "Híbrido"
        assert "CLT" in job_data.contract_type
        assert "R$ 2.800,00" in job_data.salary_range
        assert len(job_data.responsibilities) >= 3
        assert len(job_data.requirements) >= 3

        job_model = job_from_page_data(job_data, custom_id="job-logistica-sul-01")
        assert job_model.id == "job-logistica-sul-01"
        assert job_model.title == "Assistente Administrativo e Financeiro"
        assert job_model.match_level == MatchLevel.NOT_EVALUATED
        assert job_model.status == JobStatus.IDENTIFIED

        storage = JsonStorage(cfg)
        saved = storage.upsert_job(job_model)
        assert saved.id == "job-logistica-sul-01"
        assert len(storage.list_jobs()) == 1

        report = write_jobs_markdown_report(storage.list_jobs(), cfg.output_dir)
        assert report.exists()
        content = report.read_text(encoding="utf-8")
        assert "Assistente Administrativo e Financeiro" in content
        assert "Logística Sul Exemplo" in content


@pytest.mark.asyncio
async def test_search_local_job_cards(tmp_path: Path) -> None:
    cfg = _make_test_config(tmp_path)
    search_html_file = tmp_path / "mock_job_search.html"
    search_html_file.write_text(MOCK_JOB_SEARCH_HTML, encoding="utf-8")

    async with BrowserManager(cfg) as manager:
        page = await manager.get_page()
        await page.goto(search_html_file.as_uri(), wait_until="domcontentloaded")

        cards = await search_jobs_on_linkedin(page, limit=5, navigate=False)
        assert len(cards) == 2
        assert cards[0].title == "Assistente Administrativo"
        assert cards[0].company == "Transportes Rápido Ltda"
        assert cards[0].work_model == "Presencial"
        assert cards[1].title == "Analista Financeiro Júnior"
        assert cards[1].company == "Grupo Sul Alimentos"
        assert cards[1].work_model == "Híbrido"


@pytest.mark.asyncio
async def test_search_modern_job_cards(tmp_path: Path) -> None:
    cfg = _make_test_config(tmp_path)
    modern_file = tmp_path / "mock_modern_search.html"
    modern_file.write_text(MOCK_JOB_SEARCH_MODERN_HTML, encoding="utf-8")

    async with BrowserManager(cfg) as manager:
        page = await manager.get_page()
        await page.goto(modern_file.as_uri(), wait_until="domcontentloaded")

        cards = await search_jobs_on_linkedin(page, limit=5, navigate=False)
        assert len(cards) == 2
        assert cards[0].title == "Assistente administrativo Pl - POA"
        assert cards[0].company == "Konica Minolta Business Solutions do Brasil"
        assert cards[0].work_model == "Híbrido"
        assert cards[0].job_id == "job-4485316942"
        assert cards[1].title == "ASSISTENTE ADMINISTRATIVO"
        assert cards[1].company == "Coca-Cola FEMSA"
        assert cards[1].job_id == "job-4476681514"


def test_manual_job_registration_and_id_generation(tmp_path: Path) -> None:
    cfg = _make_test_config(tmp_path)
    job_id = generate_job_id("Transportes Delta", "Assistente Financeiro", "https://linkedin.com/jobs/view/99887766/")
    assert job_id == "job-99887766"

    job = register_job_manually(
        cfg,
        title="Assistente de Faturamento",
        company="Distribuidora de Alimentos RS",
        application_url="https://www.linkedin.com/jobs/view/11223344/",
        location="São Leopoldo, RS",
        work_model="Presencial",
        contract_type="CLT",
        salary_range="R$ 3.000,00",
        description="Rotinas de emissão de NF-e, conferência de fretes e conciliação bancária.",
        requirements=["Experiência com notas fiscais", "Excel intermediário"],
        responsibilities=["Emissão de NF", "Fechamento diário de faturamento"],
    )
    assert job.id == "job-11223344"
    assert job.title == "Assistente de Faturamento"
    assert job.company == "Distribuidora de Alimentos RS"

    storage = JsonStorage(cfg)
    stored_jobs = storage.list_jobs()
    assert len(stored_jobs) == 1
    assert stored_jobs[0].title == "Assistente de Faturamento"
