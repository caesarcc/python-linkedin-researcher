"""Testes de automação Playwright, sessão e extração em páginas HTML locais — Etapa 3 e 4.

Nenhum teste acessa o LinkedIn real na internet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.browser.linkedin_pages import (
    extract_company_page,
    extract_recruiter_profile_page,
    parse_experience_lines_from_text,
)
from linkedin_researcher.browser.session_manager import (
    ManualInterventionRequiredError,
    detect_security_challenge,
    is_authenticated,
)
from linkedin_researcher.config import AppConfig
from linkedin_researcher.models import Recruiter
from linkedin_researcher.research.recruiter_research import (
    apply_profile_data_to_recruiter,
    manually_update_recruiter,
    register_company_from_profile,
    write_recruiters_markdown_report,
)
from linkedin_researcher.storage import JsonStorage

MOCK_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Entrar no LinkedIn</title></head>
<body>
  <main>
    <form>
      <input type="text" name="session_key" placeholder="E-mail ou telefone" />
      <input type="password" name="session_password" placeholder="Senha" />
      <button type="submit">Entrar</button>
    </form>
  </main>
</body>
</html>
"""

MOCK_RECRUITER_PROFILE_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Caesar Cesar | LinkedIn</title></head>
<body>
  <nav id="global-nav"><a href="https://www.linkedin.com/feed/">Início</a></nav>
  <main>
    <section>
      <h1>Caesar Cesar</h1>
      <div class="text-body-medium">
        Engenheiro de Dados | Cloudera CDP | Spark | Airflow | Vagas Administrativas e Financeiras
      </div>
      <span class="text-body-small inline t-black--light break-words">
        Porto Alegre, Rio Grande do Sul, Brasil
      </span>
    </section>

    <section>
      <h2>Sobre</h2>
      <p>
        Atuo com engenharia de dados, big data e suporte a oportunidades técnicas.
      </p>
    </section>

    <section id="experience">
      <h2>Experiência</h2>
      <ul>
        <li class="artdeco-list__item">
          <a href="https://www.linkedin.com/company/vert-analytics/">
            <span aria-hidden="true">Engenheiro de Dados Sênior</span>
            <span aria-hidden="true">Vert Analytics · Tempo integral</span>
            <span aria-hidden="true">fev de 2023 - o momento · 3 anos</span>
            <span aria-hidden="true">Porto Alegre, RS · Híbrido</span>
          </a>
        </li>
      </ul>
    </section>
  </main>
</body>
</html>
"""

MOCK_COMPANY_ABOUT_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Vert Analytics: Sobre | LinkedIn</title></head>
<body>
  <nav id="global-nav"><a href="https://www.linkedin.com/feed/">Início</a></nav>
  <main>
    <section>
      <h1>Vert Analytics</h1>
      <p>
        Consultoria especializada em Engenharia de Dados, Analytics e Inteligência Artificial.
      </p>
      <dl>
        <dt>Site</dt>
        <dd>https://www.vertanalytics.com</dd>
        <dt>Setor</dt>
        <dd>Tecnologia da Informação e Dados</dd>
        <dt>Sede</dt>
        <dd>Porto Alegre, RS</dd>
      </dl>
    </section>
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


TEST_RECRUITERS = [
    Recruiter(
        id="rec-01-caesar-cesar",
        name="Caesar Cesar",
        current_title="Engenheiro de Dados",
        current_company="Pendente",
        location="Porto Alegre, RS",
        recruitment_focus=["Vagas Administrativas/Corporativas", "Vagas Financeiras"],
        company_verified=False,
        professional_context="a confirmar",
    ),
    Recruiter(
        id="rec-02-caesar-cesar-consultoria",
        name="Caesar Cesar (Consultor)",
        current_title="Consultor de Tecnologia",
        current_company="Pendente",
        location="Porto Alegre, RS",
        recruitment_focus=["Cloud Analytics"],
        company_verified=False,
        professional_context="a confirmar",
    ),
]


@pytest.mark.asyncio
async def test_session_detection_and_local_profile_extraction(tmp_path: Path) -> None:
    cfg = _make_test_config(tmp_path)
    storage = JsonStorage(cfg)
    storage.seed_initial_recruiters(TEST_RECRUITERS)

    profile_html_file = tmp_path / "mock_profile.html"
    profile_html_file.write_text(MOCK_RECRUITER_PROFILE_HTML, encoding="utf-8")

    company_html_file = tmp_path / "mock_company.html"
    company_html_file.write_text(MOCK_COMPANY_ABOUT_HTML, encoding="utf-8")

    async with BrowserManager(cfg) as manager:
        page = await manager.get_page()

        # 1. Testa detecção de tela de login (não autenticada)
        await page.set_content(MOCK_LOGIN_HTML)
        challenge = await detect_security_challenge(page)
        assert challenge is not None
        assert await is_authenticated(page) is False

        with pytest.raises(ManualInterventionRequiredError):
            await extract_recruiter_profile_page(page, navigate=False)

        # 2. Testa extração de perfil autenticado a partir de arquivo HTML local (file://)
        await page.goto(profile_html_file.as_uri(), wait_until="domcontentloaded")
        assert await is_authenticated(page) is True

        profile_data = await extract_recruiter_profile_page(
            page, profile_url=profile_html_file.as_uri(), navigate=False
        )
        assert profile_data.full_name == "Caesar Cesar"
        assert profile_data.current_company == "Vert Analytics"
        assert profile_data.company_verified is True
        assert (
            profile_data.company_linkedin_url
            == "https://www.linkedin.com/company/vert-analytics"
        )

        # 3. Atualiza recrutador e empresa no JsonStorage
        caesar = storage.get_recruiter("rec-01-caesar-cesar")
        assert caesar is not None
        updated_rec = apply_profile_data_to_recruiter(caesar, profile_data)
        saved_rec = storage.upsert_recruiter(updated_rec)

        assert saved_rec.current_company == "Vert Analytics"
        assert saved_rec.company_verified is True
        assert "Vagas Administrativas/Corporativas" in saved_rec.recruitment_focus
        assert "Vagas Financeiras" in saved_rec.recruitment_focus

        comp = register_company_from_profile(storage, profile_data)
        assert comp is not None
        assert comp.name == "Vert Analytics"

        # 4. Testa extração de página de empresa local
        await page.goto(company_html_file.as_uri(), wait_until="domcontentloaded")
        comp_data = await extract_company_page(
            page, company_url=company_html_file.as_uri(), navigate=False
        )
        assert comp_data.name == "Vert Analytics"
        assert comp_data.industry == "Tecnologia da Informação e Dados"
        assert comp_data.location == "Porto Alegre, RS"
        assert comp_data.website == "https://www.vertanalytics.com"

        report_path = write_recruiters_markdown_report(storage.list_recruiters(), cfg.output_dir)
        assert report_path.exists()
        assert "Vert Analytics" in report_path.read_text(encoding="utf-8")


def test_sdui_experience_lines_parser_and_manual_update(tmp_path: Path) -> None:
    """Valida parser de linhas da página /details/experience/ (SDUI) e confirmação manual."""
    sample_lines = [
        "Experiência",
        "Vert Analytics",
        "7 anos 10 meses",
        "Engenheiro de Dados Sênior",
        "jun. de 2024 - o momento · 2 anos 6 meses",
        "O momento",
        "Engenheiro de Dados Pleno",
        "Tempo integral",
        "fev. de 2019 - o momento · 7 anos 10 meses",
        "Porto Alegre RS",
        "O momento",
        "Analista de BI",
        "Escritório de Dados Ltda",
        "mar. de 2018 - fev. de 2019 · 1 ano",
        "Mais perfis para você",
    ]
    sample_links = [
        {
            "href": "https://www.linkedin.com/company/vert-analytics/",
            "text": "Vert Analytics",
        }
    ]
    parsed = parse_experience_lines_from_text(sample_lines, sample_links)
    assert len(parsed) == 3
    assert parsed[0].role_title == "Engenheiro de Dados Sênior"
    assert parsed[0].company_name == "Vert Analytics"
    assert parsed[0].is_current is True
    assert parsed[0].company_linkedin_url == "https://www.linkedin.com/company/vert-analytics"
    assert parsed[1].role_title == "Engenheiro de Dados Pleno"
    assert parsed[1].company_name == "Vert Analytics"
    assert parsed[2].role_title == "Analista de BI"
    assert parsed[2].company_name == "Escritório de Dados Ltda"
    assert parsed[2].is_current is False

    # Testa layout com localidade no grupo (ex: perfil Caesar Cesar)
    caesar_lines = [
        "Experiência",
        "Vert Analytics",
        "Tempo integral · 3 a 7 m",
        "Porto Alegre, Rio Grande do Sul, Brasil · No local",
        "Engenheiro de Dados Sênior",
        "fev. de 2026 - o momento · 10 meses",
        "O momento",
    ]
    caesar_links = [
        {
            "href": "https://www.linkedin.com/company/vert-analytics/",
            "text": "Vert Analytics",
        }
    ]
    caesar_parsed = parse_experience_lines_from_text(caesar_lines, caesar_links)
    assert len(caesar_parsed) == 1
    assert caesar_parsed[0].role_title == "Engenheiro de Dados Sênior"
    assert caesar_parsed[0].company_name == "Vert Analytics"
    assert caesar_parsed[0].is_current is True

    # Testa layout com duração e modalidade combinada (ex: perfil Caesar Cesar consultoria)
    caesar_alt_lines = [
        "Experiência",
        "Vert Analytics",
        "Tempo integral · 3 a 1 m",
        "Tech Lead de Dados",
        "abr. de 2025 - o momento · 1 ano 8 meses",
        "Porto Alegre, Rio Grande do Sul, Brasil · No local",
    ]
    caesar_alt_links = [
        {
            "href": "https://www.linkedin.com/company/vert-analytics/",
            "text": "Vert Analytics",
        }
    ]
    caesar_alt_parsed = parse_experience_lines_from_text(caesar_alt_lines, caesar_alt_links)
    assert len(caesar_alt_parsed) == 1
    assert caesar_alt_parsed[0].role_title == "Tech Lead de Dados"
    assert caesar_alt_parsed[0].company_name == "Vert Analytics"
    assert caesar_alt_parsed[0].is_current is True

    cfg = _make_test_config(tmp_path)
    storage = JsonStorage(cfg)
    storage.seed_initial_recruiters(TEST_RECRUITERS)
    updated = manually_update_recruiter(
        cfg,
        recruiter_id="rec-02-caesar-cesar-consultoria",
        company_name="Vert Analytics",
        verified=True,
        linkedin_url="https://www.linkedin.com/in/caesarcc/",
    )
    assert updated.current_company == "Vert Analytics"
    assert updated.company_verified is True

    storage = JsonStorage(cfg)
    companies = storage.list_companies()
    assert any(c.id == "comp-vert-analytics" for c in companies)
