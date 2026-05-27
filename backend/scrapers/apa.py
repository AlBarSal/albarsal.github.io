"""
APA Call for Papers scraper.

APA's page at apa.org/pubs/journals/resources/calls-for-papers is protected by
Incapsula WAF. We use Playwright (headless Chromium) to fetch the page with a
real browser fingerprint, then parse the rendered HTML with BeautifulSoup.

Falls back to httpx if Playwright is unavailable.
"""

import logging
import re
from typing import List, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, extract_date, make_id

logger = logging.getLogger(__name__)

BASE_URL = "https://www.apa.org"
URL = f"{BASE_URL}/pubs/journals/resources/calls-for-papers"

_LOAD_TIMEOUT_MS = 30_000


class APAScraper(BaseScraper):
    source_name = "APA"
    url = URL

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        logger.info("[%s] Starting scrape of %s", self.source_name, self.url)

        # Try Playwright (bypasses Incapsula)
        try:
            import playwright  # noqa: F401
            cfps, error = await self._scrape_playwright()
            if cfps:
                logger.info("[%s] Playwright found %d CFPs", self.source_name, len(cfps))
                return cfps, ScrapingStatus(
                    source_id=self.source_id, source=self.source_name, success=True, count=len(cfps)
                )
            if error:
                logger.warning("[%s] Playwright: %s", self.source_name, error)
        except ImportError:
            logger.warning("[%s] Playwright not installed; falling back to httpx", self.source_name)
        except Exception as exc:
            logger.error("[%s] Playwright error: %s", self.source_name, exc)

        # httpx fallback
        soup = await self.fetch(self.url)
        if soup is None:
            return [], ScrapingStatus(
                source_id=self.source_id, source=self.source_name, success=False, count=0,
                error="No se pudo acceder a la página (bloqueado por WAF)"
            )

        text = clean(soup.get_text())
        if "incapsula" in text.lower() or len(text) < 200:
            return [], ScrapingStatus(
                source_id=self.source_id, source=self.source_name, success=False, count=0,
                error="Acceso bloqueado por el WAF de APA. Playwright es requerido."
            )

        cfps = self._parse_soup(soup)
        logger.info("[%s] httpx found %d CFPs", self.source_name, len(cfps))
        return cfps, ScrapingStatus(
            source_id=self.source_id, source=self.source_name, success=True, count=len(cfps)
        )

    # ── Playwright ────────────────────────────────────────────────────────────

    async def _scrape_playwright(self) -> tuple[List[CallForPaper], str | None]:
        from playwright.async_api import async_playwright  # noqa: PLC0415

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-User": "?1",
                        "Sec-Fetch-Dest": "document",
                    },
                )
                page = await ctx.new_page()

                logger.info("[%s] Playwright: navigating to %s", self.source_name, self.url)
                resp = await page.goto(
                    self.url, wait_until="domcontentloaded", timeout=_LOAD_TIMEOUT_MS
                )

                if resp and resp.status >= 400:
                    return [], f"HTTP {resp.status} from APA"

                # Wait for the main content to load
                await page.wait_for_timeout(2000)

                content = await page.content()
            finally:
                await browser.close()

        soup = BeautifulSoup(content, "lxml")

        # Check for Incapsula block
        body_text = clean(soup.get_text())
        if "incapsula" in body_text.lower() or len(body_text) < 200:
            return [], "Acceso bloqueado por Incapsula incluso con Playwright"

        cfps = self._parse_soup(soup)
        return cfps, None

    # ── Parse HTML ────────────────────────────────────────────────────────────

    def _parse_soup(self, soup: BeautifulSoup) -> List[CallForPaper]:
        cfps = (
            self._strategy_drupal_views(soup)
            or self._strategy_list_items(soup)
            or self._strategy_headings(soup)
            or self._strategy_links(soup)
        )
        # Deduplicate
        seen: set[str] = set()
        return [c for c in cfps if not (c.id in seen or seen.add(c.id))]  # type: ignore

    def _strategy_drupal_views(self, soup: BeautifulSoup) -> List[CallForPaper]:
        rows = soup.find_all(
            "div", class_=lambda c: c and "views-row" in " ".join(c) if c else False
        )
        if not rows:
            container = soup.find(
                "div", class_=lambda c: c and "view-content" in " ".join(c) if c else False
            )
            if container:
                rows = container.find_all(["div", "article", "li"])
        if not rows:
            return []
        return [r for r in (self._parse_drupal_row(row) for row in rows) if r]

    def _strategy_list_items(self, soup: BeautifulSoup) -> List[CallForPaper]:
        main = (
            soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(
                "div",
                class_=lambda c: c and "content" in " ".join(c).lower() if c else False,
            )
            or soup
        )
        results = []
        for li in main.find_all("li"):
            link = li.find("a", href=True)
            if not link:
                continue
            title = clean(link.get_text())
            if len(title) < 8:
                continue
            url = self._make_absolute(link["href"], BASE_URL)
            full_text = clean(li.get_text())
            deadline = extract_date(full_text)
            desc_text = full_text.replace(title, "").strip()
            results.append(
                CallForPaper(
                    id=make_id(self.source_name, title),
                    title=title,
                    source=self.source_name,
                    deadline=deadline,
                    description=self._truncate(desc_text) if desc_text else "No disponible",
                    url=url,
                )
            )
        return results

    def _strategy_headings(self, soup: BeautifulSoup) -> List[CallForPaper]:
        main = (
            soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup
        )
        results = []
        for tag in main.find_all(["h2", "h3", "h4"]):
            link = tag.find("a", href=True)
            if not link:
                continue
            title = clean(tag.get_text())
            if len(title) < 8:
                continue
            url = self._make_absolute(link["href"], BASE_URL)
            parent = tag.parent or tag
            full_text = clean(parent.get_text())
            deadline = extract_date(full_text)
            desc_tag = tag.find_next_sibling(["p", "div"])
            description = clean(desc_tag.get_text()) if desc_tag else "No disponible"
            results.append(
                CallForPaper(
                    id=make_id(self.source_name, title),
                    title=title,
                    source=self.source_name,
                    deadline=deadline,
                    description=self._truncate(description),
                    url=url,
                )
            )
        return results

    def _strategy_links(self, soup: BeautifulSoup) -> List[CallForPaper]:
        results = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if not any(kw in href for kw in ("/journals/", "/pubs/", "call")):
                continue
            title = clean(a.get_text())
            if len(title) < 8:
                continue
            url = self._make_absolute(href, BASE_URL)
            results.append(
                CallForPaper(
                    id=make_id(self.source_name, title),
                    title=title,
                    source=self.source_name,
                    url=url,
                )
            )
        return results[:50]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _parse_drupal_row(self, row: Tag) -> CallForPaper | None:
        title_tag = (
            row.find(
                class_=lambda c: c and "title" in " ".join(c).lower() if c else False
            )
            or row.find(["h2", "h3", "h4"])
        )
        link = None
        if title_tag:
            link = title_tag.find("a", href=True)
            title = clean(title_tag.get_text())
        else:
            link = row.find("a", href=True)
            title = clean(link.get_text()) if link else ""

        if not title or len(title) < 5:
            return None

        url = self._make_absolute(link["href"] if link else "", BASE_URL)
        full_text = clean(row.get_text())

        deadline_tag = row.find(
            class_=lambda c: c and any(
                t in " ".join(c).lower() for t in ("deadline", "date", "field-date", "due")
            ) if c else False
        )
        deadline = (
            clean(deadline_tag.get_text())
            if deadline_tag
            else extract_date(full_text)
        )

        journal_tag = row.find(
            class_=lambda c: c and any(
                t in " ".join(c).lower() for t in ("journal", "publication", "field-journal")
            ) if c else False
        )
        journal = clean(journal_tag.get_text()) if journal_tag else "No disponible"

        body_tag = (
            row.find(
                class_=lambda c: c and any(
                    t in " ".join(c).lower()
                    for t in ("body", "description", "summary", "field-body", "teaser")
                ) if c else False
            )
            or row.find("p")
        )
        description = clean(body_tag.get_text()) if body_tag else "No disponible"
        if description == title:
            description = "No disponible"

        return CallForPaper(
            id=make_id(self.source_name, title),
            title=title,
            source=self.source_name,
            journal=journal,
            deadline=deadline,
            description=self._truncate(description),
            url=url,
        )
