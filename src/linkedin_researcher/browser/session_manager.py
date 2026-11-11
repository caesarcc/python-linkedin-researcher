"""Gerenciador de sessão persistente, verificação de login e detecção de desafios — Etapa 3."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_researcher.browser.browser_manager import BrowserManager
from linkedin_researcher.config import AppConfig

logger = logging.getLogger("linkedin_researcher.browser.session")

LINKEDIN_BASE_URL = "https://www.linkedin.com"
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"


class ManualInterventionRequiredError(RuntimeError):
    """Exceção lançada quando o LinkedIn exige login manual, MFA, CAPTCHA ou verificação."""


async def detect_security_challenge(page: Page) -> str | None:
    """Verifica se a página atual apresenta tela de login, MFA, CAPTCHA ou bloqueio.

    Nunca tenta resolver ou contornar desafios; retorna a descrição para pausa imediata.
    """
    current_url = (page.url or "").lower()
    parsed = urlparse(current_url)
    path = parsed.path

    if any(token in path for token in ("/checkpoint/", "/challenge/", "/waf/")):
        return (
            f"Desafio de segurança ou verificação (MFA/CAPTCHA) detectado na URL: {page.url}. "
            "Conclua a verificação manualmente no navegador."
        )

    if any(token in path for token in ("/login", "/uas/login", "/authwall", "/signup")):
        return f"Sessão não autenticada (redirecionado para tela de login/authwall: {page.url})."

    try:
        title = (await page.title()).lower()
    except PlaywrightError:
        title = ""

    challenge_keywords = (
        "verificação de segurança",
        "security verification",
        "desafio de segurança",
        "confirme sua identidade",
        "let's do a quick security check",
    )
    if any(kw in title for kw in challenge_keywords):
        return f"Desafio de segurança detectado no título da página ('{title}')."

    # Verifica presença de formulário de login quando a URL parece pública mas exige login
    try:
        has_password_input = await page.locator("input[type='password']").count() > 0
        has_global_nav = (
            await page.locator("#global-nav, nav.global-nav, a[href*='/feed/']").count() > 0
        )
        if has_password_input and not has_global_nav:
            return "Formulário de login detectado na página atual. Autenticação manual necessária."
    except PlaywrightError:
        pass

    return None


async def is_authenticated(page: Page) -> bool:
    """Retorna True se a página atual estiver em uma sessão autenticada do LinkedIn."""
    challenge = await detect_security_challenge(page)
    if challenge is not None:
        return False

    current_url = (page.url or "").lower()
    if not current_url.startswith(("http://", "https://", "file://")):
        return False

    # Verifica marcos semânticos da área logada do LinkedIn
    authenticated_selectors = (
        "#global-nav",
        "nav.global-nav",
        "a[href*='/feed/']",
        "a[href*='/mynetwork/']",
        "a[href*='/messaging/']",
        "input[placeholder*='Pesquisar']",
        "input[placeholder*='Search']",
        "[data-test-global-nav]",
    )
    for sel in authenticated_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except PlaywrightError:
            continue

    # Se estiver em /feed/ sem ter caído em login/checkpoint
    parsed_path = urlparse(current_url).path
    if parsed_path.startswith("/feed"):
        return True

    return False


async def ensure_authenticated(page: Page) -> None:
    """Garante que a sessão atual está autenticada antes de uma pesquisa.

    Se não estiver autenticada ou houver desafio, lança ManualInterventionRequiredError.
    """
    current_url = page.url or ""
    if not current_url or current_url == "about:blank":
        logger.info("Verificando sessão autenticada em %s...", LINKEDIN_FEED_URL)
        try:
            await page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise ManualInterventionRequiredError(
                f"Timeout ao carregar {LINKEDIN_FEED_URL}. Verifique sua conexão."
            ) from exc

    challenge = await detect_security_challenge(page)
    if challenge is not None:
        raise ManualInterventionRequiredError(
            f"{challenge}\n"
            "Execute 'linkedin-researcher browser login' para autenticar manualmente."
        )

    if not await is_authenticated(page):
        raise ManualInterventionRequiredError(
            "Sessão do LinkedIn não está autenticada. "
            "Execute 'linkedin-researcher browser login' para fazer o login manual."
        )


async def interactive_login(config: AppConfig, max_wait_seconds: int = 300) -> bool:
    """Abre o navegador em modo visível (headed) para login manual pela titular da conta.

    Aguarda até que a autenticação seja detectada (ou até max_wait_seconds) e persiste
    automaticamente o estado no diretório `.playwright-profile/`.
    """
    print("\n=== Login Manual Assistido — LinkedIn ===")
    print(f"Perfil persistente local: {config.user_data_dir}")
    print("1. Uma janela do navegador será aberta no LinkedIn.")
    print("2. Faça o login manualmente (e conclua eventual verificação/MFA se solicitada).")
    print(
        "3. Assim que o feed principal carregar, a sessão será validada e salva automaticamente.\n"
    )

    async with BrowserManager(config, force_headed=True) as manager:
        page = await manager.get_page()
        await page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")

        if await is_authenticated(page):
            print("[OK] Sessão já estava autenticada! Estado preservado no perfil local.")
            await asyncio.sleep(2.0)
            return True

        print("Aguardando conclusão do login manual na janela do navegador...")
        elapsed = 0
        poll_interval = 2
        while elapsed < max_wait_seconds:
            if page.is_closed():
                print("[AVISO] A janela do navegador foi fechada antes da confirmação do login.")
                return False

            if await is_authenticated(page):
                # Aguarda 3 segundos extras para garantir gravação de cookies no perfil persistente
                await asyncio.sleep(3.0)
                print(
                    "\n[OK] Login manual detectado com sucesso! "
                    f"Sessão salva em: {config.user_data_dir}"
                )
                return True

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        print(
            f"\n[TEMPO ESGOTADO] Não foi detectado login após {max_wait_seconds}s. "
            "Você pode executar o comando novamente quando desejar."
        )
        return False
