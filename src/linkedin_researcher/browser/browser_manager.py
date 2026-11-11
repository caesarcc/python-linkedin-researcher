"""Gerenciador de ciclo de vida do Playwright e BrowserContext persistente — Etapa 3."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path
from types import TracebackType

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

from linkedin_researcher.config import AppConfig

logger = logging.getLogger("linkedin_researcher.browser.manager")


class BrowserManager:
    """Gerencia o ciclo de vida assíncrono do Playwright com perfil persistente local.

    Segue as diretrizes de segurança do projeto:
    - Isola dados de sessão em `config.user_data_dir` (`.playwright-profile/`, ignorado pelo Git).
    - Não utiliza técnicas de ocultação, proxies ou adulteração de fingerprint.
    - Garante encerramento limpo do contexto mesmo em caso de erro.
    """

    def __init__(self, config: AppConfig, force_headed: bool = False) -> None:
        self.config = config
        self.force_headed = force_headed
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("BrowserManager ainda não foi iniciado. Use 'async with'.")
        return self._context

    async def start(self) -> BrowserContext:
        """Inicia o Playwright e abre o contexto persistente dedicado."""
        self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
        headless = False if self.force_headed else self.config.headless

        self._playwright = await async_playwright().start()

        channels_to_try: list[str | None] = []
        if self.config.browser_channel:
            channels_to_try.append(self.config.browser_channel)
        for fallback_ch in ("chrome", "msedge", None):
            if fallback_ch not in channels_to_try:
                channels_to_try.append(fallback_ch)

        last_error: Exception | None = None
        for channel in channels_to_try:
            try:
                launch_kwargs: dict[str, object] = {
                    "user_data_dir": str(self.config.user_data_dir),
                    "headless": headless,
                    "viewport": {"width": 1280, "height": 840},
                    "locale": "pt-BR",
                }
                if channel is not None:
                    launch_kwargs["channel"] = channel

                logger.info(
                    "Iniciando contexto persistente do navegador (channel=%s, headless=%s, dir=%s)",
                    channel or "chromium-bundled",
                    headless,
                    self.config.user_data_dir,
                )
                self._context = await self._playwright.chromium.launch_persistent_context(
                    **launch_kwargs  # type: ignore[arg-type]
                )
                self._context.set_default_timeout(self.config.default_timeout_ms)
                self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
                return self._context
            except Exception as exc:
                last_error = exc
                logger.debug("Canal %s indisponível (%s), tentando próximo...", channel, exc)

        await self.close()
        raise RuntimeError(
            f"Não foi possível iniciar o navegador Playwright. Último erro: {last_error}"
        )

    async def get_page(self) -> Page:
        """Retorna a primeira aba aberta no contexto ou cria uma nova."""
        ctx = self.context
        if ctx.pages:
            return ctx.pages[0]
        return await ctx.new_page()

    async def respectful_delay(self, reason: str = "navegação pontual") -> float:
        """Aguarda intervalo configurável entre requisições para uso ético e de baixo volume."""
        low = max(0.0, self.config.min_action_delay_sec)
        high = max(low, self.config.max_action_delay_sec)
        delay = random.uniform(low, high)
        if delay > 0:
            logger.info("Aguardando %.1fs (%s)...", delay, reason)
            await asyncio.sleep(delay)
        return delay

    async def capture_diagnostic_screenshot(self, page: Page, prefix: str = "diag") -> Path | None:
        """Salva screenshot técnico em logs/ (ignorado pelo Git) em caso de falha de layout."""
        try:
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.config.logs_dir / f"{prefix}_{ts}.png"
            await page.screenshot(path=str(path), full_page=False)
            logger.info("Screenshot de diagnóstico salvo em: %s", path)
            return path
        except PlaywrightError as exc:
            logger.warning("Não foi possível capturar screenshot de diagnóstico: %s", exc)
            return None

    async def close(self) -> None:
        """Fecha o contexto persistente e encerra a instância do Playwright."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug("Aviso ao fechar BrowserContext: %s", exc)
            finally:
                self._context = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug("Aviso ao encerrar Playwright: %s", exc)
            finally:
                self._playwright = None

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
