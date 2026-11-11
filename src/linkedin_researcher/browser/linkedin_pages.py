"""Seletores semânticos resilientes e extração estruturada de páginas do LinkedIn — Etapa 3 e 4.

Este módulo contém exclusivamente lógica de leitura e extração passiva de páginas.
Nenhuma função clica em botões de envio de mensagem, convite de conexão ou candidatura.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote_plus, urljoin

from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    Page,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from linkedin_researcher.browser.session_manager import (
    LINKEDIN_BASE_URL,
    ManualInterventionRequiredError,
    detect_security_challenge,
)

logger = logging.getLogger("linkedin_researcher.browser.pages")

EMPLOYMENT_SUFFIX_RE = re.compile(
    r"\s*·\s*(tempo integral|meio per[íi]odo|aut[ôo]nomo|freelance|terceirizado|"
    r"est[áa]gio|aprendiz|tempor[áa]rio|full-time|part-time|self-employed|contract|internship).*$",
    re.IGNORECASE,
)

CURRENT_DATE_MARKER_RE = re.compile(
    r"\b(o momento|atual|atualmente|present|presente|current)\b",
    re.IGNORECASE,
)

DATE_RANGE_LINE_RE = re.compile(
    r"(?:\b(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|"
    r"feb|apr|may|aug|sep|oct|dec)[a-z.]*\s+(?:de\s+)?\d{4}|\b(?:19|20)\d{2})"
    r"\s*[-–]\s*"
    r"(?:o momento|atual|atualmente|present|presente|current|"
    r"(?:[a-z.]+\s+(?:de\s+)?)?(?:19|20)\d{2})",
    re.IGNORECASE,
)

DURATION_ONLY_RE = re.compile(
    r"^\d+\s*(?:ano|anos|a|m[êe]s|meses|m|yr|yrs|mo|mos)\b",
    re.IGNORECASE,
)

DURATION_OR_EMPLOYMENT_RE = re.compile(
    r"(?:tempo integral|meio per[íi]odo|aut[ôo]nomo|freelance|terceirizado|"
    r"est[áa]gio|aprendiz|tempor[áa]rio|full-time|part-time|self-employed|"
    r"contract|internship|\d+\s*(?:ano|anos|a|m[êe]s|meses|m|yr|yrs|mo|mos))\b",
    re.IGNORECASE,
)

LOCATION_LINE_RE = re.compile(
    r"(?:,\s*(?:RS|PR|SC|SP|RJ|MG|Brasil|Brazil|Rio Grande do Sul|Paran[áa]|"
    r"Santa Catarina|S[ãa]o Paulo)|[·•]\s*(?:No local|H[íi]brido|Remoto|Presencial|"
    r"On-site|Hybrid|Remote)|\bNo local\b|\bPresencial\b|\bRemoto\b|\bH[íi]brido\b)",
    re.IGNORECASE,
)

EMPLOYMENT_TYPE_ONLY_RE = re.compile(
    r"^(?:tempo integral|meio per[íi]odo|aut[ôo]nomo|freelance|terceirizado|"
    r"est[áa]gio|aprendiz|tempor[áa]rio|full-time|part-time|self-employed|"
    r"contract|internship)$",
    re.IGNORECASE,
)

MORE_COMPANIES_SUFFIX_RE = re.compile(
    r"\s+(?:e\s+mais\s+\d+\s+empresas?|and\s+\d+\s+more.*)$",
    re.IGNORECASE,
)

HEADLINE_COMPANY_RE = re.compile(
    r"(?:\b(?:na|no|at|@|founder da|founder na|fundador(?:a)? da|s[óo]cio(?:a)? da)\s+)"
    r"([A-ZÀ-Ú0-9][A-Za-zÀ-ÿ0-9\s&\.\-]{1,45}?)(?:\s*[|\•·,/]|$)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _norm_token(text: str) -> str:
    cleaned = _strip_accents(text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", cleaned).split())


def _clean_company_name(raw: str) -> str:
    """Remove sufixos de modalidade de contratação e contadores do nome da empresa."""
    text = " ".join(raw.split()).strip()
    text = EMPLOYMENT_SUFFIX_RE.sub("", text).strip(" ·-|•")
    text = MORE_COMPANIES_SUFFIX_RE.sub("", text).strip(" ·-|•")
    return text


def _canonical_profile_url(href: str) -> str | None:
    if not href:
        return None
    full = urljoin(LINKEDIN_BASE_URL, href.strip())
    match = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[^/?#]+)", full, re.IGNORECASE)
    if match:
        return match.group(1).rstrip("/")
    if full.startswith("file://"):
        return full
    return None


def _canonical_company_url(href: str) -> str | None:
    if not href:
        return None
    full = urljoin(LINKEDIN_BASE_URL, href.strip())
    match = re.search(r"(https?://(?:www\.)?linkedin\.com/company/[^/?#]+)", full, re.IGNORECASE)
    if match:
        return match.group(1).rstrip("/")
    if full.startswith("file://"):
        return full
    return None


def _canonical_job_url(href: str) -> str | None:
    """Retorna URL canônica da vaga no LinkedIn (/jobs/view/<id>/) limpa de tracking."""
    if not href:
        return None
    full = urljoin(LINKEDIN_BASE_URL, href.strip())
    # Trata formato direto /jobs/view/<id>
    match = re.search(
        r"(https?://(?:www\.)?linkedin\.com/jobs/view/(?:\d+|[^/?#]+))",
        full,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).rstrip("/") + "/"
    # Trata formato com parâmetro currentJobId=<id>
    current_id_m = re.search(r"currentJobId=(\d+)", full)
    if current_id_m:
        return f"{LINKEDIN_BASE_URL}/jobs/view/{current_id_m.group(1)}/"
    if full.startswith("file://"):
        return full
    return None


@dataclass
class JobSearchItem:
    """Card resumido de vaga retornado na busca de empregos do LinkedIn."""

    job_id: str
    title: str
    company: str
    location: str
    job_url: str
    work_model: str = "a confirmar"


@dataclass
class JobPageData:
    """Dados completos extraídos da página de detalhes da vaga (/jobs/view/<id>/)."""

    source_url: str
    checked_at: str
    title: str = ""
    company: str = ""
    location: str = "a confirmar"
    work_model: str = "a confirmar"
    contract_type: str = "a confirmar"
    salary_range: str = "Não informado"
    description: str = ""
    requirements: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    published_at: str | None = None
    extraction_notes: list[str] = field(default_factory=list)


@dataclass
class SearchCandidateResult:
    """Representa um candidato encontrado na busca de pessoas do LinkedIn."""

    name: str
    profile_url: str
    card_snippet: str = ""
    current_company_hint: str | None = None
    match_score: int = 0


@dataclass
class ExperienceItemData:
    """Representa um item extraído da seção Experiência de um perfil."""

    role_title: str
    company_name: str
    date_range: str = ""
    is_current: bool = False
    company_linkedin_url: str | None = None


@dataclass
class ProfilePageData:
    """Dados estruturados extraídos de uma página de perfil de recrutador."""

    source_url: str
    checked_at: str
    full_name: str = ""
    headline: str = ""
    location: str = ""
    current_company: str | None = None
    current_role_title: str | None = None
    company_verified: bool = False
    company_linkedin_url: str | None = None
    about_text: str = ""
    experiences: list[ExperienceItemData] = field(default_factory=list)
    extraction_notes: list[str] = field(default_factory=list)


@dataclass
class CompanyPageData:
    """Dados estruturados extraídos de uma página de empresa no LinkedIn."""

    source_url: str
    checked_at: str
    name: str = ""
    industry: str = "a confirmar"
    location: str = "a confirmar"
    website: str | None = None
    work_model: str = "a confirmar"
    description: str = ""
    extraction_notes: list[str] = field(default_factory=list)


async def search_recruiter_on_linkedin(
    page: Page,
    name: str,
    location_hint: str = "",
    title_hint: str = "",
) -> SearchCandidateResult | None:
    """Pesquisa um recrutador pelo nome na busca do LinkedIn e retorna o melhor perfil."""
    search_url = f"{LINKEDIN_BASE_URL}/search/results/people/?keywords={quote_plus(name)}"
    logger.info("Pesquisando perfil de '%s' em: %s", name, search_url)

    try:
        await page.goto(search_url, wait_until="domcontentloaded")
    except PlaywrightTimeoutError as exc:
        logger.warning("Timeout ao abrir busca para '%s': %s", name, exc)
        return None

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    try:
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
        await asyncio.sleep(1.5)
    except PlaywrightTimeoutError:
        logger.warning("Elemento <main> não ficou visível na busca por '%s'.", name)
        return None

    # Extrai candidatos da página de resultados a partir dos links /in/ dentro de <main>
    raw_candidates: list[dict[str, str]] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const anchors = Array.from(main.querySelectorAll('a[href*="/in/"]'));
            const seen = new Set();
            const results = [];
            const cardSel = [
                'li',
                '[data-view-name="search-entity-result-universal-template"]',
                '.reusable-search__result-container'
            ].join(', ');
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                if (!href.includes('/in/') || href.includes('/miniProfile')) continue;
                const cleanUrl = href.split('?')[0].replace(/\\/+$/, '');
                if (seen.has(cleanUrl)) continue;

                const card = a.closest(cardSel) || a.parentElement;
                const rawName = (a.innerText || a.textContent || '').trim();
                const cardText = card ? (card.innerText || card.textContent || '').trim() : rawName;
                if (!rawName && !cardText) continue;

                seen.add(cleanUrl);
                results.push({
                    href: cleanUrl,
                    rawName: rawName,
                    cardText: cardText
                });
            }
            return results;
        }"""
    )

    if not raw_candidates:
        logger.info("Nenhum link '/in/' encontrado na busca para '%s'.", name)
        return None

    target_tokens = _norm_token(name).split()
    loc_city = _norm_token(location_hint.split(",")[0]) if location_hint else ""
    title_words = [w for w in _norm_token(title_hint).split() if len(w) >= 3]

    best: SearchCandidateResult | None = None
    for item in raw_candidates:
        profile_url = _canonical_profile_url(item.get("href", ""))
        if not profile_url:
            continue

        card_text = " ".join((item.get("cardText") or "").split())
        raw_name_lines = [
            line.strip()
            for line in (item.get("rawName") or "").splitlines()
            if line.strip() and not line.strip().lower().startswith("ver perfil")
        ]
        candidate_name = raw_name_lines[0] if raw_name_lines else name
        candidate_name = re.sub(r"\s*[•·]\s*(1º|2º|3º\+?).*$", "", candidate_name).strip()

        haystack_norm = _norm_token(f"{candidate_name} {card_text}")
        matched_name_tokens = sum(1 for tok in target_tokens if tok in haystack_norm)
        if matched_name_tokens == 0:
            continue

        score = matched_name_tokens * 25
        if all(tok in haystack_norm for tok in target_tokens):
            score += 40
        if loc_city and loc_city in haystack_norm:
            score += 15
        score += sum(5 for tw in title_words[:5] if tw in haystack_norm)

        # Verifica se o card da busca já exibe "Atual: ... na Empresa"
        company_hint: str | None = None
        atual_match = re.search(
            r"(?:Atual|Current)\s*:\s*.*?\b(?:na|no|at|em)\s+([^\n•·|]{2,50})",
            card_text,
            re.IGNORECASE,
        )
        if atual_match:
            company_hint = _clean_company_name(atual_match.group(1))

        candidate = SearchCandidateResult(
            name=candidate_name,
            profile_url=profile_url,
            card_snippet=card_text[:500],
            current_company_hint=company_hint,
            match_score=score,
        )
        if best is None or candidate.match_score > best.match_score:
            best = candidate

    return best


def parse_experience_lines_from_text(
    lines: list[str],
    company_links: list[dict[str, str]] | None = None,
) -> list[ExperienceItemData]:
    """Interpreta linhas visíveis da página /details/experience/ ou seção Experiência SDUI."""
    stop_markers = {
        "mais perfis para voce",
        "pessoas que talvez voce conheca",
        "conheca perfis premium",
        "voce talvez goste",
        "exibir mais",
        "exibir tudo",
    }
    clean_lines: list[str] = []
    started = False
    for raw_line in lines:
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        norm = _norm_token(line)
        if not started:
            if norm in {"experiencia", "experience"}:
                started = True
                continue
            started = True
        if norm in stop_markers:
            break
        clean_lines.append(line)

    # Mapa de URL de empresa a partir dos links coletados na página de experiência
    default_comp_url: str | None = None
    company_url_by_norm: dict[str, str] = {}
    for link in company_links or []:
        c_url = _canonical_company_url(str(link.get("href") or ""))
        c_txt = _clean_company_name(str(link.get("text") or ""))
        if not c_url:
            continue
        if default_comp_url is None:
            default_comp_url = c_url
        if c_txt:
            company_url_by_norm[_norm_token(c_txt)] = c_url

    results: list[ExperienceItemData] = []
    active_group_company: str | None = None
    active_group_url: str | None = None

    for idx, line in enumerate(clean_lines):
        if not DATE_RANGE_LINE_RE.search(line):
            continue

        # Coleta linhas candidatas acima do período de datas, descartando ruídos e metadados
        candidate_lines: list[str] = []
        for i in range(idx - 1, max(-1, idx - 7), -1):
            c_line = clean_lines[i]
            if DATE_RANGE_LINE_RE.search(c_line) or c_line.lower() == "o momento":
                break
            candidate_lines.append(c_line)

        content_lines: list[str] = []
        for cl in candidate_lines:
            is_meta = bool(DURATION_OR_EMPLOYMENT_RE.search(cl) and len(cl) < 45)
            is_loc = bool(LOCATION_LINE_RE.search(cl) and len(cl) < 70)
            if not is_meta and not is_loc:
                content_lines.append(cl)

        has_group_header = any(
            DURATION_OR_EMPLOYMENT_RE.search(cl) for cl in candidate_lines
        )

        role_title = ""
        company_name = ""

        if has_group_header:
            if content_lines:
                role_title = content_lines[0]
                company_name = (
                    _clean_company_name(content_lines[-1])
                    if len(content_lines) >= 2
                    else (active_group_company or "")
                )
                if company_name:
                    active_group_company = company_name
        else:
            if len(content_lines) >= 2:
                company_name = _clean_company_name(content_lines[0])
                role_title = content_lines[1]
                active_group_company = None
                active_group_url = None
            elif len(content_lines) == 1:
                role_title = content_lines[0]
                company_name = active_group_company or ""

        if not role_title or not company_name:
            continue

        comp_norm = _norm_token(company_name)
        matched_url = company_url_by_norm.get(comp_norm)
        if not matched_url:
            for k_norm, u_val in company_url_by_norm.items():
                if comp_norm and (comp_norm in k_norm or k_norm in comp_norm):
                    matched_url = u_val
                    break
        if matched_url and active_group_company == company_name:
            active_group_url = matched_url
        elif not matched_url and active_group_company == company_name:
            matched_url = active_group_url or default_comp_url

        is_current = bool(CURRENT_DATE_MARKER_RE.search(line))
        results.append(
            ExperienceItemData(
                role_title=role_title,
                company_name=company_name,
                date_range=line,
                is_current=is_current,
                company_linkedin_url=matched_url,
            )
        )

    return results


async def _extract_experiences_from_details_page(
    page: Page,
    canonical_profile: str,
) -> list[ExperienceItemData]:
    """Navega até /in/<slug>/details/experience/ quando a seção principal não hidratou."""
    details_url = f"{canonical_profile.rstrip('/')}/details/experience/"
    logger.info("Consultando detalhes de experiência em: %s", details_url)
    try:
        await page.goto(details_url, wait_until="domcontentloaded")
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
        await asyncio.sleep(2.5)
    except PlaywrightError as exc:
        logger.warning("Não foi possível carregar %s: %s", details_url, exc)
        return []

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    raw_details: dict[str, object] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const lines = (main.innerText || '')
                .split('\\n')
                .map(l => clean(l))
                .filter(Boolean);
            const anchors = Array.from(main.querySelectorAll('a[href*="/company/"]'));
            const companyLinks = anchors.map(a => ({
                href: a.getAttribute('href') || '',
                text: clean(a.innerText)
            }));
            return { lines, companyLinks };
        }"""
    )
    lines_raw = [str(x) for x in (raw_details.get("lines") or []) if str(x).strip()]
    links_raw = [
        x for x in (raw_details.get("companyLinks") or []) if isinstance(x, dict)
    ]
    return parse_experience_lines_from_text(lines_raw, links_raw)


async def extract_recruiter_profile_page(
    page: Page,
    profile_url: str | None = None,
    navigate: bool = True,
) -> ProfilePageData:
    """Navega (se solicitado) e extrai nome, headline, local, empresa atual e experiências."""
    if navigate and profile_url:
        logger.info("Acessando perfil: %s", profile_url)
        try:
            await page.goto(profile_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise PlaywrightError(f"Timeout ao carregar perfil {profile_url}: {exc}") from exc

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    checked_at = _now_iso()
    source_url = page.url or (profile_url or "")

    try:
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise PlaywrightError(
            f"Conteúdo principal (<main>) não carregou no perfil {source_url}."
        ) from exc

    # Em páginas reais do LinkedIn, aguardar hidratação inicial e rolar a janela
    if source_url.startswith("http"):
        try:
            await asyncio.sleep(2.5)
            await page.evaluate("window.scrollBy(0, 700)")
            await asyncio.sleep(1.5)
        except PlaywrightError:
            pass

    raw_data: dict[str, object] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();

            const rawTitle = (document.title || '').split('|')[0].replace(/^\\(\\d+\\)\\s*/, '');
            const titleName = clean(rawTitle);
            const h1 = main.querySelector('h1');
            let fullName = clean(h1 ? h1.innerText : '');

            const allSections = Array.from(main.querySelectorAll('section'));
            let topSection = (h1 && h1.closest('section')) || null;
            const nonProfileH2Re = new RegExp(
                '^(Sobre|About|Atividades|Activity|Experi[êe]ncia|Experience|' +
                'Mais perfis|Conhe[çc]a|Pessoas que|Voc[êe] talvez|Op[çc][õo]es|N[ãa]o quero)',
                'i'
            );

            if (!fullName) {
                for (const sec of allSections) {
                    const h2 = sec.querySelector('h2');
                    const h2Text = clean(h2 ? h2.innerText : '');
                    if (!h2Text) continue;
                    const tLow = titleName.toLowerCase();
                    const matchesTitle = titleName && h2Text.toLowerCase() === tLow;
                    if (matchesTitle || !nonProfileH2Re.test(h2Text)) {
                        fullName = h2Text;
                        if (sec.querySelectorAll('section').length <= 2) {
                            topSection = sec;
                            break;
                        }
                    }
                }
            }
            if (!fullName && titleName && !/linkedin/i.test(titleName)) {
                fullName = titleName;
            }
            if (!topSection) {
                const isCard = s => s.querySelectorAll('section').length <= 2;
                const candidateSec = allSections.find(isCard);
                topSection = candidateSec || allSections[0] || null;
            }

            let headline = '';
            let location = '';
            let topCardCompany = '';
            let topCardCompanyUrl = '';

            if (topSection) {
                const hSel = [
                    '.text-body-medium',
                    '[data-generated-suggestion-target]',
                    '.pv-text-details__left-panel div'
                ].join(', ');
                const headlineEl = topSection.querySelector(hSel);
                if (headlineEl && headlineEl !== h1) {
                    headline = clean(headlineEl.innerText);
                }

                const lSel = [
                    '.text-body-small.inline.t-black--light.break-words',
                    '.pv-text-details__left-panel span.text-body-small'
                ].join(', ');
                const locEl = topSection.querySelector(lSel);
                if (locEl) {
                    location = clean(locEl.innerText);
                }

                // Linhas visíveis do top card (compatível com layout clássico e SDUI novo)
                const topLines = (topSection.innerText || '')
                    .split('\\n')
                    .map(l => clean(l))
                    .filter(Boolean);

                if (!headline && topLines.length > 1) {
                    const fLow = fullName.toLowerCase();
                    const nameIdx = topLines.findIndex(l => l.toLowerCase() === fLow);
                    if (nameIdx >= 0) {
                        const maxIdx = Math.min(topLines.length, nameIdx + 5);
                        for (let i = nameIdx + 1; i < maxIdx; i++) {
                            const cand = topLines[i];
                            const isDot = cand === '·' || cand === '•';
                            const isBadge = /^[·•]\\s*\\d/i.test(cand) || isDot;
                            if (isBadge) continue;
                            headline = cand;
                            break;
                        }
                    }
                }
                if (!location) {
                    const locRe = new RegExp(
                        ',\\\\s*(RS|PR|SC|SP|RJ|MG|Brasil|Brazil|Rio Grande do Sul|' +
                        'Paran[áa]|Santa Catarina|S[ãa]o Paulo)',
                        'i'
                    );
                    const locLine = topLines.find(
                        l => locRe.test(l) && !l.startsWith('Contratando')
                    );
                    if (locLine) location = locLine;
                }

                // 1) Botão de empresa atual no topo do perfil
                const cBtnSel = [
                    'button[aria-label*="Empresa atual"]',
                    'button[aria-label*="Current company"]',
                    '[data-field="experience_company_logo"]'
                ].join(', ');
                const companyBtn = topSection.querySelector(cBtnSel);
                if (companyBtn) {
                    const aria = companyBtn.getAttribute('aria-label') || '';
                    const m = aria.match(/(?:Empresa atual|Current company)\\s*:\\s*([^.]+)/i);
                    topCardCompany = m
                        ? clean(m[1].replace(/\\.\\s*Clique.*$/i, ''))
                        : clean(companyBtn.innerText);
                }

                // 2) Linha após "Dados de contato" / "Contact info" no layout SDUI
                if (!topCardCompany) {
                    const contactRe = /^(Dados de contato|Contact info)$/i;
                    const contactIdx = topLines.findIndex(l => contactRe.test(l));
                    if (contactIdx >= 0 && topLines[contactIdx + 1]) {
                        const afterContact = topLines[contactIdx + 1];
                        const skipRe = new RegExp(
                            'seguidores|conex[õo]es|followers|connections|' +
                            'enviar mensagem|conectar|seguir|http',
                            'i'
                        );
                        if (!skipRe.test(afterContact)) {
                            topCardCompany = afterContact;
                        }
                    }
                }

                // 3) Card "Contratando: <Vaga>" -> linha seguinte "<Empresa> · <Local>"
                const hiringIdx = topLines.findIndex(l => /^Contratando\\s*:/i.test(l));
                if (hiringIdx >= 0 && topLines[hiringIdx + 1]) {
                    const hiringCompany = clean(topLines[hiringIdx + 1].split('·')[0]);
                    if (!topCardCompany && hiringCompany) {
                        topCardCompany = hiringCompany;
                    }
                }

                // 4) Link /company/ no topSection
                const compLink = topSection.querySelector('a[href*="/company/"]');
                if (compLink) {
                    topCardCompanyUrl = compLink.getAttribute('href') || '';
                    if (!topCardCompany) {
                        topCardCompany = clean(compLink.innerText);
                    }
                }
            }

            // Localizar seções por heading (Sobre / Experiência) e links de empresa do perfil
            let aboutText = '';
            const experiences = [];
            const recSecRe = new RegExp(
                '^(Voc[êe] talvez goste|Mais perfis|Pessoas que talvez|Conhe[çc]a perfis)',
                'i'
            );

            for (const sec of allSections) {
                const headings = Array.from(sec.querySelectorAll('h2, h3, [role="heading"]'))
                    .map(h => clean(h.innerText))
                    .filter(Boolean);
                if (headings.length === 0) continue;

                // Evitar que a seção wrapper externa sobrescreva seções internas específicas
                const isWrapper = sec.querySelectorAll('section').length > 1;
                const headingText = headings[0];

                if (!isWrapper && /^(Sobre|About)\\b/i.test(headingText)) {
                    const withoutHead = sec.innerText.replace(headingText, '');
                    const rawAbout = withoutHead.replace(/…\\s*mais$/i, '');
                    aboutText = clean(rawAbout).slice(0, 800);
                }

                const isExp = !isWrapper && /^(Experi[êe]ncia|Experience)\\b/i.test(headingText);
                if (isExp || sec.id === 'experience') {
                    const liSel = 'ul > li.artdeco-list__item, ul > li';
                    const items = Array.from(sec.querySelectorAll(liSel));
                    for (const li of items.slice(0, 6)) {
                        const spanEls = li.querySelectorAll('span[aria-hidden="true"]');
                        const visibleSpans = Array.from(spanEls)
                            .map(s => clean(s.innerText))
                            .filter(Boolean);
                        const lines = visibleSpans.length >= 2
                            ? visibleSpans
                            : (li.innerText || '')
                                .split('\\n')
                                .map(l => clean(l))
                                .filter(Boolean);

                        const compAnchor = li.querySelector('a[href*="/company/"]');
                        const compHref = compAnchor ? (compAnchor.getAttribute('href') || '') : '';

                        if (lines.length >= 2) {
                            experiences.push({
                                lines: lines.slice(0, 8),
                                companyHref: compHref
                            });
                        }
                    }
                }

                // Se ainda não capturamos URL da empresa do topo, procurar nas seções próprias
                if (!topCardCompanyUrl && !isWrapper && !recSecRe.test(headingText)) {
                    const secCompLink = sec.querySelector('a[href*="/company/"]');
                    if (secCompLink) {
                        const cText = clean(secCompLink.innerText);
                        const cHref = secCompLink.getAttribute('href') || '';
                        const topLow = topCardCompany.toLowerCase();
                        const matchesTop = cText && topLow.includes(cText.toLowerCase());
                        if (!topCardCompany || matchesTop) {
                            topCardCompanyUrl = cHref;
                            if (!topCardCompany && cText) topCardCompany = cText;
                        }
                    }
                }
            }

            return {
                fullName,
                headline,
                location,
                topCardCompany,
                topCardCompanyUrl,
                aboutText,
                experiences
            };
        }"""
    )

    canonical_prof = _canonical_profile_url(source_url) or source_url
    data = ProfilePageData(
        source_url=canonical_prof,
        checked_at=checked_at,
        full_name=str(raw_data.get("fullName") or ""),
        headline=str(raw_data.get("headline") or ""),
        location=str(raw_data.get("location") or ""),
        about_text=str(raw_data.get("aboutText") or ""),
    )

    if not data.full_name:
        data.extraction_notes.append("Nome principal não encontrado no cabeçalho do perfil.")

    # Processar itens da seção Experiência (quando presentes no DOM principal)
    raw_exps = raw_data.get("experiences")
    if isinstance(raw_exps, list):
        for raw_item in raw_exps:
            if not isinstance(raw_item, dict):
                continue
            lines = [str(x) for x in (raw_item.get("lines") or []) if str(x).strip()]
            comp_href = _canonical_company_url(str(raw_item.get("companyHref") or ""))
            if len(lines) < 2:
                continue

            is_grouped = bool(
                DURATION_ONLY_RE.search(lines[1])
                or re.search(r"^Tempo integral|^Full-time", lines[1], re.I)
            )
            if is_grouped and len(lines) >= 3:
                company_name = _clean_company_name(lines[0])
                role_title = lines[2]
                date_line = next(
                    (
                        ln
                        for ln in lines[2:]
                        if re.search(r"\b(19|20)\d{2}\b|momento|atual|present", ln, re.I)
                    ),
                    "",
                )
            else:
                role_title = lines[0]
                company_name = _clean_company_name(lines[1])
                date_line = next(
                    (
                        ln
                        for ln in lines[2:]
                        if re.search(r"\b(19|20)\d{2}\b|momento|atual|present", ln, re.I)
                    ),
                    lines[2] if len(lines) > 2 else "",
                )

            is_current = bool(CURRENT_DATE_MARKER_RE.search(date_line))
            exp_entry = ExperienceItemData(
                role_title=role_title,
                company_name=company_name,
                date_range=date_line,
                is_current=is_current,
                company_linkedin_url=comp_href,
            )
            data.experiences.append(exp_entry)

    # No layout SDUI atual do LinkedIn, a seção Experiência requer abrir /details/experience/
    if (
        not data.experiences
        and navigate
        and canonical_prof.startswith("http")
        and "/in/" in canonical_prof
    ):
        details_exps = await _extract_experiences_from_details_page(page, canonical_prof)
        if details_exps:
            data.experiences.extend(details_exps)

    top_company = _clean_company_name(str(raw_data.get("topCardCompany") or ""))
    top_company_url = _canonical_company_url(str(raw_data.get("topCardCompanyUrl") or ""))

    # Determinar empresa atual com prioridade para evidência verificada na seção Experiência
    current_exp = next((e for e in data.experiences if e.is_current and e.company_name), None)
    if current_exp is not None:
        data.current_company = current_exp.company_name
        data.current_role_title = current_exp.role_title
        data.company_linkedin_url = top_company_url or current_exp.company_linkedin_url
        data.company_verified = True
        data.extraction_notes.append(
            f"Empresa atual confirmada na seção Experiência "
            f"({current_exp.role_title} — {current_exp.date_range})."
        )
    elif top_company:
        data.current_company = top_company
        data.company_linkedin_url = top_company_url
        data.company_verified = True
        data.extraction_notes.append("Empresa atual identificada no cabeçalho do perfil.")
    elif data.experiences:
        first_exp = data.experiences[0]
        data.current_company = first_exp.company_name
        data.current_role_title = first_exp.role_title
        data.company_linkedin_url = first_exp.company_linkedin_url
        has_closed_range = bool(
            re.search(r"\b(19|20)\d{2}\b.*[-–].*\b(19|20)\d{2}\b", first_exp.date_range)
        )
        data.company_verified = not has_closed_range
        data.extraction_notes.append(
            f"Extraída experiência mais recente do perfil ({first_exp.company_name})."
        )
    else:
        headline_match = HEADLINE_COMPANY_RE.search(data.headline)
        if headline_match:
            hint_comp = _clean_company_name(headline_match.group(1))
            data.current_company = f"{hint_comp} (mencionada no título; confirmar vínculo)"
            data.company_verified = False
            data.extraction_notes.append(
                "Seção Experiência não disponível; empresa mencionada apenas no headline."
            )
        else:
            data.extraction_notes.append(
                "Não foi possível confirmar empresa atual visível no perfil."
            )

    return data


async def search_company_on_linkedin(
    page: Page,
    company_name: str,
) -> str | None:
    """Pesquisa uma empresa pelo nome e retorna a URL canônica (/company/<slug>)."""
    encoded = quote_plus(company_name)
    search_url = f"{LINKEDIN_BASE_URL}/search/results/companies/?keywords={encoded}"
    logger.info("Pesquisando empresa '%s' em: %s", company_name, search_url)
    try:
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
        await asyncio.sleep(1.5)
    except PlaywrightError as exc:
        logger.warning("Timeout ou erro na busca da empresa '%s': %s", company_name, exc)
        return None

    raw_links: list[dict[str, str]] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const anchors = Array.from(main.querySelectorAll('a[href*="/company/"]'));
            const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
            return anchors.map(a => ({
                href: a.getAttribute('href') || '',
                text: clean(a.innerText)
            })).filter(x => x.href && !x.href.includes('/setup/') && !x.href.includes('/job/'));
        }"""
    )

    comp_tokens = _norm_token(company_name).split()
    for item in raw_links:
        u = _canonical_company_url(item.get("href", ""))
        t = _norm_token(item.get("text", ""))
        if u and any(tok in t for tok in comp_tokens):
            return u
    return None


async def extract_company_page(
    page: Page,
    company_url: str,
    navigate: bool = True,
) -> CompanyPageData:
    """Extrai dados básicos institucionais de uma página de empresa no LinkedIn."""
    target_url = company_url
    if (
        navigate
        and company_url.startswith("http")
        and not company_url.rstrip("/").endswith("/about")
    ):
        target_url = f"{company_url.rstrip('/')}/about/"

    if navigate:
        logger.info("Acessando página da empresa: %s", target_url)
        try:
            await page.goto(target_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise PlaywrightError(f"Timeout ao carregar empresa {target_url}: {exc}") from exc

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    checked_at = _now_iso()
    source_url = page.url or target_url

    try:
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise PlaywrightError(f"Elemento <main> não carregou na empresa {source_url}.") from exc

    raw_comp: dict[str, str] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const h1 = main.querySelector('h1') || document.querySelector('h1');
            let name = clean(h1 ? h1.innerText : '');

            // Fallback para nome da empresa a partir do título do documento
            if (!name) {
                const titleParts = (document.title || '').split(':');
                if (titleParts.length > 0 && !titleParts[0].toLowerCase().includes('linkedin')) {
                    name = clean(titleParts[0].split('|')[0]);
                }
            }

            let description = '';
            const pSel = 'section p, .org-page-details__definition-text';
            const pList = Array.from(main.querySelectorAll(pSel));
            if (pList.length > 0) {
                description = clean(pList.map(p => p.innerText).join(' ')).slice(0, 800);
            }

            let website = '';
            let industry = '';
            let location = '';

            const dts = Array.from(main.querySelectorAll('dt, .org-page-details__definition-term'));
            for (const dt of dts) {
                const label = clean(dt.innerText).toLowerCase();
                const dd = dt.nextElementSibling;
                const val = clean(dd ? dd.innerText : '');
                if (!val) continue;
                if (label.includes('site') || label.includes('website')) {
                    website = val.split(' ')[0];
                }
                if (label.includes('setor') || label.includes('industry')) industry = val;
                if (label.includes('sede') || label.includes('headquarters')) location = val;
            }

            return { name, description, website, industry, location };
        }"""
    )

    website_raw = raw_comp.get("website") or None
    if website_raw and not website_raw.startswith(("http://", "https://")):
        website_raw = f"https://{website_raw}"

    return CompanyPageData(
        source_url=source_url,
        checked_at=checked_at,
        name=raw_comp.get("name") or "",
        industry=raw_comp.get("industry") or "a confirmar",
        location=raw_comp.get("location") or "a confirmar",
        website=website_raw,
        description=raw_comp.get("description") or "",
    )


async def search_jobs_on_linkedin(
    page: Page,
    keywords: str = "Assistente Administrativo",
    location: str = "Porto Alegre, RS",
    remote_only: bool = False,
    limit: int = 5,
    navigate: bool = True,
) -> list[JobSearchItem]:
    """Pesquisa vagas de emprego no LinkedIn e retorna cards resumidos encontrados."""
    encoded_kw = quote_plus(keywords)
    encoded_loc = quote_plus(location)
    search_url = f"{LINKEDIN_BASE_URL}/jobs/search/?keywords={encoded_kw}&location={encoded_loc}"
    if remote_only:
        search_url += "&f_WT=2"

    if navigate:
        logger.info("Pesquisando vagas: '%s' em '%s' -> %s", keywords, location, search_url)
        try:
            await page.goto(search_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            logger.warning("Timeout ao abrir busca de vagas: %s", exc)
            return []

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    try:
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
        if navigate:
            await asyncio.sleep(2.5)
    except PlaywrightTimeoutError:
        logger.warning("Elemento <main> não carregou na busca de vagas.")
        return []

    raw_items: list[dict[str, str]] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
            const results = [];
            const seenIds = new Set();

            // 1. Estrutura moderna (Pesquisa por IA / Layout novo do LinkedIn)
            const modernCards = Array.from(main.querySelectorAll(
                '[data-view-name="job-search-job-card"], [componentkey*="job-card-component-ref-"]'
            ));
            for (const el of modernCards) {
                const ckEl = el.querySelector('[componentkey*="job-card-component-ref-"]') || el;
                const ck = ckEl.getAttribute('componentkey') || '';
                const idMatch = ck.match(/ref-(\\d+)/);
                const numId = idMatch ? idMatch[1] : '';
                if (numId && seenIds.has(numId)) continue;

                const lines = (el.innerText || '').split('\\n').map(clean).filter(Boolean);
                if (lines.length < 2) continue;

                let title = lines[0];
                if (title.startsWith('Selecionada,') || title.startsWith('Visto')) {
                    title = lines.length > 1 ? lines[1] : title;
                }
                title = title.replace(/\\(Vaga verificada\\)/gi, '').trim();

                let company = '';
                let loc = '';
                for (let i = 1; i < Math.min(lines.length, 5); i++) {
                    const ln = lines[i];
                    if (ln === title || ln.startsWith('Selecionada,') || ln === 'Visto') continue;
                    if (!company) {
                        company = ln;
                        continue;
                    }
                    if (!loc && (
                        ln.includes('RS') || ln.includes('Brasil') ||
                        ln.includes('Região') || ln.includes('(')
                    )) {
                        loc = ln;
                        break;
                    }
                }

                if (numId) seenIds.add(numId);
                const href = numId ? `https://www.linkedin.com/jobs/view/${numId}/` : '';
                results.push({ href, title, company, location: loc });
            }

            // 2. Estrutura clássica (.job-card-container, base-card)
            const classicCards = Array.from(main.querySelectorAll(
                'li, div.job-card-container, div.base-card, .jobs-search-results__list-item'
            ));
            for (const card of classicCards) {
                const link = card.querySelector(
                    'a[href*="/jobs/view/"], a.job-card-container__link, ' +
                    'a.job-card-list__title--link, a.base-card__full-link'
                );
                if (!link) continue;
                const href = link.getAttribute('href') || '';
                if (!href || href.includes('/help') || href.includes('/login')) continue;

                const idMatch = href.match(/(?:\\/jobs\\/view\\/|currentJobId=)(\\d+)/);
                const numId = idMatch ? idMatch[1] : null;
                if (numId && seenIds.has(numId)) continue;

                let title = clean(link.innerText);
                if (!title) {
                    const tEl = card.querySelector('.job-card-list__title, h3, strong');
                    if (tEl) title = clean(tEl.innerText);
                }
                if (!title) continue;

                let company = '';
                const compEl = card.querySelector(
                    '.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, ' +
                    '.base-search-card__subtitle, a[href*="/company/"]'
                );
                if (compEl) company = clean(compEl.innerText);

                let location = '';
                const locEl = card.querySelector(
                    '.job-card-container__metadata-item, .job-search-card__location, ' +
                    '.artdeco-entity-lockup__caption'
                );
                if (locEl) location = clean(locEl.innerText);

                if (numId) seenIds.add(numId);
                results.push({ href, title, company, location });
            }

            // 3. Links diretos com currentJobId ou bullet " • " (Feed de vagas recomendadas)
            const feedAnchors = Array.from(main.querySelectorAll('a[href*="currentJobId="]'));
            for (const a of feedAnchors) {
                const href = a.getAttribute('href') || '';
                const idMatch = href.match(/currentJobId=(\\d+)/);
                if (!idMatch) continue;
                const numId = idMatch[1];
                if (seenIds.has(numId)) continue;

                const text = clean(a.innerText);
                if (!text.includes(' • ')) continue;

                const parts = text.split(' • ');
                const before = parts[0].trim();
                const after = parts.slice(1).join(' • ').trim();

                const lines = before.split(' ');
                let company = before;
                let title = '';
                if (lines.length > 2) {
                    company = lines.slice(-2).join(' ');
                    title = lines.slice(0, -2).join(' ');
                }

                seenIds.add(numId);
                results.push({
                    href: `https://www.linkedin.com/jobs/view/${numId}/`,
                    title: title || before,
                    company: company,
                    location: after
                });
            }

            return results;
        }"""
    )

    items: list[JobSearchItem] = []
    seen_urls: set[str] = set()

    for raw in raw_items:
        c_url = _canonical_job_url(raw.get("href", ""))
        if not c_url or c_url in seen_urls:
            continue
        seen_urls.add(c_url)

        title = raw.get("title", "").strip()
        comp = _clean_company_name(raw.get("company", "").strip()) or "Empresa Confidencial"
        loc = raw.get("location", "").strip() or "a confirmar"

        work_model = "a confirmar"
        combined_text = f"{title} {loc}".lower()
        if "remoto" in combined_text or "remote" in combined_text:
            work_model = "Remoto"
        elif any(k in combined_text for k in ("híbrido", "hibrido", "hybrid")):
            work_model = "Híbrido"
        elif any(k in combined_text for k in ("presencial", "no local", "on-site")):
            work_model = "Presencial"

        # Gera ID derivado do id numérico ou do título/empresa
        num_m = re.search(r"/jobs/view/(\d+)", c_url)
        job_id = f"job-{num_m.group(1)}" if num_m else f"job-{len(items) + 1:02d}"

        items.append(
            JobSearchItem(
                job_id=job_id,
                title=title,
                company=comp,
                location=loc,
                job_url=c_url,
                work_model=work_model,
            )
        )
        if len(items) >= limit:
            break

    return items


def _parse_job_sections(description: str) -> tuple[list[str], list[str]]:
    """Extrai requisitos e responsabilidades estruturados do texto livre da vaga."""
    reqs: list[str] = []
    resps: list[str] = []
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]

    current_section: str | None = None
    for ln in lines:
        lower = ln.lower()
        if any(h in lower for h in ("requisito", "o que você precisa", "o que buscamos")):
            current_section = "req"
            continue
        if any(h in lower for h in ("atividades", "responsabilidade", "o que você vai fazer")):
            current_section = "resp"
            continue

        clean_item = re.sub(r"^[\s•·\-\*✓\d\.\)\-]+", "", ln).strip()
        if not clean_item or len(clean_item) < 4:
            continue

        if current_section == "req" and len(reqs) < 10:
            reqs.append(clean_item)
        elif current_section == "resp" and len(resps) < 10:
            resps.append(clean_item)

    return reqs, resps


async def extract_job_page(
    page: Page,
    job_url: str,
    navigate: bool = True,
) -> JobPageData:
    """Extrai informações completas e estruturadas da página de uma vaga (/jobs/view/<id>/)."""
    if navigate:
        logger.info("Acessando página da vaga: %s", job_url)
        try:
            await page.goto(job_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise PlaywrightError(f"Timeout ao carregar vaga {job_url}: {exc}") from exc

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(challenge)

    checked_at = _now_iso()
    source_url = page.url or job_url

    try:
        await page.locator("main").first.wait_for(state="visible", timeout=15_000)
        await asyncio.sleep(1.5)
    except PlaywrightTimeoutError as exc:
        raise PlaywrightError(f"Elemento <main> não carregou na vaga {source_url}.") from exc

    raw_job: dict[str, object] = await page.evaluate(
        """() => {
            const main = document.querySelector('main') || document.body;
            const clean = s => (s || '').replace(/\\s+/g, ' ').trim();

            const h1 = main.querySelector('h1') || document.querySelector('h1');
            let title = clean(h1 ? h1.innerText : '');
            if (!title) {
                const titleParts = (document.title || '').split('|')[0].split('-');
                if (titleParts.length > 0) title = clean(titleParts[0]);
            }

            let company = '';
            const compEl = main.querySelector(
                '.job-details-jobs-unified-top-card__company-name a, ' +
                'a[href*="/company/"], .jobs-unified-top-card__company-name'
            );
            if (compEl) company = clean(compEl.innerText);

            const topSel = [
                '.job-details-jobs-unified-top-card__primary-description-container',
                '.jobs-unified-top-card__primary-description',
                '.job-details-jobs-unified-top-card__primary-description'
            ].join(', ');
            const topEl = main.querySelector(topSel);
            const topText = clean(topEl ? topEl.innerText : '');

            const bSel = [
                '.job-details-jobs-unified-top-card__bullet',
                '.jobs-unified-top-card__bullet'
            ].join(', ');
            const bullets = Array.from(main.querySelectorAll(bSel))
                .map(b => clean(b.innerText)).filter(Boolean);

            const insights = Array.from(main.querySelectorAll(
                '.job-details-jobs-unified-top-card__job-insight, ' +
                'li.job-details-jobs-unified-top-card__job-insight'
            )).map(i => clean(i.innerText)).filter(Boolean);

            const descEl = main.querySelector(
                'article.jobs-description__container, #job-details, ' +
                '.jobs-description-content__text, .jobs-box__html-content'
            );
            const description = descEl ? (descEl.innerText || '').trim() : '';

            const cleanLines = (main.innerText || document.body.innerText || '')
                .split('\\n')
                .map(clean)
                .filter(Boolean);

            return {
                title,
                company,
                topText,
                bullets,
                insights,
                description,
                docTitle: document.title || '',
                cleanLines
            };
        }"""
    )

    doc_title = str(raw_job.get("docTitle") or "")
    clean_lines = [str(x) for x in (raw_job.get("cleanLines") or [])]
    title = str(raw_job.get("title") or "").strip()
    company = _clean_company_name(str(raw_job.get("company") or "").strip())
    top_text = str(raw_job.get("topText") or "")
    description = str(raw_job.get("description") or "").strip()
    insights = [str(x) for x in (raw_job.get("insights") or [])]
    bullets = [str(x) for x in (raw_job.get("bullets") or [])]

    # Refinamento de título a partir do título da janela ou primeiras linhas
    if not title and doc_title:
        title = doc_title.split("|")[0].strip()
    if not title and len(clean_lines) >= 2:
        title = clean_lines[1]
    title = re.sub(r"^Selecionada,\s*", "", title, flags=re.I).strip()
    title = re.sub(r"\(Vaga verificada\)", "", title, flags=re.I).strip()

    # Refinamento de empresa a partir do documento ou primeiras linhas
    if not company and len(clean_lines) >= 1:
        first = clean_lines[0]
        if first != title and first.lower() not in {
            "pular para conteúdo principal",
            "início",
            "vagas",
        }:
            company = _clean_company_name(first)
    if not company and doc_title and "|" in doc_title:
        doc_parts = [p.strip() for p in doc_title.split("|") if p.strip()]
        if len(doc_parts) >= 2 and "linkedin" not in doc_parts[1].lower():
            company = _clean_company_name(doc_parts[1])
        elif len(doc_parts) >= 3 and "linkedin" not in doc_parts[2].lower():
            company = _clean_company_name(doc_parts[2])

    # Identifica modalidade de trabalho (Remoto / Híbrido / Presencial)
    # 1. Verifica correspondência exata nas linhas superiores do topo
    work_model = "a confirmar"
    for ln in clean_lines[:15]:
        ln_norm = ln.casefold().strip()
        if ln_norm in {"híbrido", "hibrido", "hybrid"}:
            work_model = "Híbrido"
            break
        if ln_norm in {"presencial", "no local", "on-site"}:
            work_model = "Presencial"
            break
        if ln_norm in {"remoto", "remote"}:
            work_model = "Remoto"
            break

    # 2. Fallback por contexto textual caso não haja linha isolada
    if work_model == "a confirmar":
        haystack_mode = f"{top_text} {' '.join(bullets)} {' '.join(insights)} {title}".lower()
        if "híbrido" in haystack_mode or "hibrido" in haystack_mode or "hybrid" in haystack_mode:
            work_model = "Híbrido"
        elif "presencial" in haystack_mode or "no local" in haystack_mode:
            work_model = "Presencial"
        elif "remoto" in haystack_mode or "remote" in haystack_mode:
            work_model = "Remoto"

    # Identifica tipo de contratação
    contract_type = "a confirmar"
    for ln in clean_lines[:15]:
        ln_norm = ln.casefold().strip()
        if any(k in ln_norm for k in ("tempo integral", "full-time", "efetivo", "clt")):
            contract_type = "Tempo integral (CLT)"
            break
        if any(k in ln_norm for k in ("meio período", "part-time")):
            contract_type = "Meio período"
            break
        if any(k in ln_norm for k in ("pj", "autônomo")):
            contract_type = "PJ"
            break

    if contract_type == "a confirmar":
        haystack_contract = f"{top_text} {' '.join(bullets)} {' '.join(insights)}".lower()
        if any(k in haystack_contract for k in ("tempo integral", "full-time", "efetivo", "clt")):
            contract_type = "Tempo integral (CLT)"
        elif any(k in haystack_contract for k in ("meio período", "part-time")):
            contract_type = "Meio período"
        elif any(k in haystack_contract for k in ("pj", "prestador de serviço", "autônomo")):
            contract_type = "PJ"

    # Localização
    location = "a confirmar"
    for b in bullets:
        if any(uf in b for uf in ("RS", "PR", "SC", "SP", "Brasil", "Brazil", "Rio Grande do Sul")):
            location = b
            break
    if location == "a confirmar" and top_text:
        loc_m = re.search(r"([^·\n]+,\s*(?:RS|PR|SC|SP|Brasil|Brazil))", top_text, re.I)
        if loc_m:
            location = loc_m.group(1).strip()
    if location == "a confirmar":
        loc_indicators = ("RS", "Região", "Brasil", "Porto Alegre", "Canoas", "São Paulo", "SP")
        for ln in clean_lines[:12]:
            if " · " in ln and any(k in ln for k in loc_indicators):
                location = ln.split(" · ")[0].strip()
                break

    # Faixa salarial se informada
    salary_range = "Não informado"
    sal_m = re.search(
        r"(?:R\$\s*[\d\.,]+(?:\s*(?:a|até|-)\s*R\$\s*[\d\.,]+)?|"
        r"sal[áa]rio\s*:\s*[^\n,]+)",
        f"{description} {' '.join(insights)} {' '.join(clean_lines[:25])}",
        re.I,
    )
    if sal_m:
        salary_range = sal_m.group(0).strip()

    # Data de publicação
    published_at: str | None = None
    pub_m = re.search(
        r"(?:há\s+\d+\s+(?:dias?|semanas?|meses|horas?))",
        f"{top_text} {' '.join(clean_lines[:15])}",
        re.I,
    )
    if pub_m:
        published_at = pub_m.group(0).strip()

    reqs, resps = _parse_job_sections(description)

    # Extração complementar a partir de clean_lines caso description não tenha separado
    if not reqs or not resps:
        current_sec: str | None = None
        desc_collected: list[str] = []
        for ln in clean_lines:
            lower = ln.lower().strip()
            if lower in {"sobre a vaga", "descrição da vaga", "sobre a oportunidade"}:
                current_sec = "desc"
                continue
            resp_headers = (
                "responsabilidades",
                "atividades",
                "o que você vai fazer",
                "principais atividades",
            )
            if any(lower.startswith(h) for h in resp_headers):
                current_sec = "resp"
                continue
            req_headers = (
                "requisitos",
                "o que buscamos",
                "o que você precisa",
                "qualificações",
            )
            if any(lower.startswith(h) for h in req_headers):
                current_sec = "req"
                continue
            other_headers = (
                "diferenciais",
                "informações adicionais",
                "benefícios",
                "ative um alerta",
                "desativada",
            )
            if any(lower.startswith(h) for h in other_headers):
                if current_sec in {"resp", "req"}:
                    current_sec = "other"
                    continue

            clean_item = re.sub(r"^[\s•·\-\*✓\d\.\)\-]+", "", ln).strip()
            if not clean_item or len(clean_item) < 4:
                continue

            if current_sec == "desc" and len(desc_collected) < 8:
                desc_collected.append(ln)
            elif current_sec == "resp" and len(resps) < 12:
                resps.append(clean_item)
            elif current_sec == "req" and len(reqs) < 12:
                reqs.append(clean_item)

        if not description and desc_collected:
            description = "\n\n".join(desc_collected)

    canonical_job = _canonical_job_url(source_url) or source_url
    return JobPageData(
        source_url=canonical_job,
        checked_at=checked_at,
        title=title,
        company=company,
        location=location,
        work_model=work_model,
        contract_type=contract_type,
        salary_range=salary_range,
        description=description,
        requirements=reqs,
        responsibilities=resps,
        published_at=published_at,
    )
