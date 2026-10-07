"""Download das páginas da OLX.

HttpxFetcher: rápido e leve; headers de navegador real, rotação de
User-Agent, pausas aleatórias e retry com backoff.
PlaywrightFetcher: navegador de verdade (Chromium) para quando a OLX
bloquear o httpx. AutoFetcher tenta o primeiro e cai para o segundo.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Protocol

import httpx

from app import config
from app.scraper.parser import BlockedError, looks_blocked

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
]


def _headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.olx.com.br/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }


def polite_sleep(delay_range: tuple[float, float] = config.REQUEST_DELAY_RANGE) -> None:
    time.sleep(random.uniform(*delay_range))


class Fetcher(Protocol):
    mode: str

    def get(self, url: str) -> str: ...
    def close(self) -> None: ...


class HttpxFetcher:
    mode = "httpx"

    def __init__(self, delay_range=config.REQUEST_DELAY_RANGE, max_retries=config.MAX_RETRIES):
        self.delay_range = delay_range
        self.max_retries = max_retries
        # Um UA por sessão (trocar a cada request parece MAIS robô, não menos)
        self.client = httpx.Client(
            headers=_headers(random.choice(USER_AGENTS)),
            timeout=config.REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self._first = True

    def get(self, url: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            if not self._first:
                polite_sleep(self.delay_range)
            self._first = False
            try:
                resp = self.client.get(url)
                if resp.status_code in (403, 429) or looks_blocked(resp.text):
                    # Troca de identidade antes de tentar de novo
                    self.client.headers.update(_headers(random.choice(USER_AGENTS)))
                    raise BlockedError(f"HTTP {resp.status_code} em {url}")
                resp.raise_for_status()
                return resp.text
            except (httpx.HTTPError, BlockedError) as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                backoff = (2 ** attempt) + random.uniform(0, 2)
                log.warning("Tentativa %s/%s falhou (%s); aguardando %.1fs",
                            attempt, self.max_retries, exc, backoff)
                time.sleep(backoff)
        if isinstance(last_exc, BlockedError):
            raise last_exc
        raise BlockedError(str(last_exc)) from last_exc

    def close(self) -> None:
        self.client.close()


class PlaywrightFetcher:
    """Requer: pip install playwright && playwright install chromium.
    Usa playwright-stealth se estiver instalado."""
    mode = "playwright"

    def __init__(self, headless: bool = True, delay_range=config.REQUEST_DELAY_RANGE):
        from playwright.sync_api import sync_playwright  # import tardio: dependência opcional

        self.delay_range = delay_range
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"])
        self._context = self._browser.new_context(
            user_agent=random.choice([u for u in USER_AGENTS if "Chrome" in u]),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 850},
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        self._page = self._context.new_page()
        try:  # playwright-stealth 2.x
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(self._context)
        except ImportError:
            try:  # playwright-stealth 1.x
                from playwright_stealth import stealth_sync
                stealth_sync(self._page)
            except ImportError:
                pass
        self._first = True

    def get(self, url: str) -> str:
        if not self._first:
            polite_sleep(self.delay_range)
        self._first = False
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Pequena rolagem: algumas listas carregam sob demanda
        self._page.mouse.wheel(0, random.randint(800, 2000))
        self._page.wait_for_timeout(random.randint(1200, 2500))
        html = self._page.content()
        if looks_blocked(html):
            raise BlockedError(f"Playwright também bloqueado em {url}")
        return html

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()


class AutoFetcher:
    """httpx primeiro; no primeiro bloqueio troca para Playwright de vez."""

    def __init__(self):
        self._impl: Fetcher = HttpxFetcher()

    @property
    def mode(self) -> str:
        return self._impl.mode

    def get(self, url: str) -> str:
        try:
            return self._impl.get(url)
        except BlockedError:
            if isinstance(self._impl, PlaywrightFetcher):
                raise
            log.warning("httpx bloqueado; trocando para Playwright")
            self._impl.close()
            try:
                self._impl = PlaywrightFetcher()
            except ImportError as exc:
                raise BlockedError(
                    "Bloqueado e Playwright não instalado "
                    "(pip install playwright && playwright install chromium)") from exc
            return self._impl.get(url)

    def close(self) -> None:
        self._impl.close()


def make_fetcher(mode: str = config.FETCH_MODE) -> Fetcher:
    if mode == "httpx":
        return HttpxFetcher()
    if mode == "playwright":
        return PlaywrightFetcher()
    return AutoFetcher()
