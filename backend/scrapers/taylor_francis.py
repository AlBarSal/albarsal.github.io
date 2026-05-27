"""
Taylor & Francis Call for Papers scraper.

Uses the public WordPress REST API at think.taylorandfrancis.com which exposes
584 "special issues" (= calls for papers / themed journal issues) with clean
structured data. Individual pages are fetched concurrently to extract the
journal name, deadlines, and description.
"""

import asyncio
import logging
import re
from typing import List, Tuple

import httpx
from bs4 import BeautifulSoup

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, extract_date, make_id

logger = logging.getLogger(__name__)

BASE_URL = "https://authorservices.taylorandfrancis.com"
THINK_BASE = "https://think.taylorandfrancis.com"
THINK_API = f"{THINK_BASE}/wp-json/wp/v2/special_issues"

_PAGE_SIZE = 100          # items per API page
_MAX_DETAIL_FETCH = 60    # individual pages to fetch for full details
_CONCURRENCY = 8          # parallel HTTP requests for detail pages


class TaylorFrancisScraper(BaseScraper):
    source_name = "Taylor & Francis"
    url = BASE_URL + "/call-for-papers/"

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        api_url = self.settings.get("api_url", THINK_API)
        page_size = int(self.settings.get("page_size", _PAGE_SIZE))
        max_pages = int(self.settings.get("max_pages", 10))
        max_detail_fetch = int(self.settings.get("max_detail_fetch", _MAX_DETAIL_FETCH))
        concurrency = int(self.settings.get("concurrency", _CONCURRENCY))

        logger.info("[%s] Fetching special issues from %s", self.source_name, api_url)

        try:
            api_items = await self._fetch_all_api_items(api_url, page_size, max_pages)
            logger.info("[%s] API returned %d special issues", self.source_name, len(api_items))
        except Exception as exc:
            logger.error("[%s] API fetch failed: %s", self.source_name, exc)
            return [], ScrapingStatus(
                source_id=self.source_id, source=self.source_name, success=False, count=0, error=str(exc)
            )

        if not api_items:
            return [], ScrapingStatus(
                source_id=self.source_id, source=self.source_name, success=False, count=0,
                error="La API no devolvió ningún resultado"
            )

        # Fetch individual pages for the freshest items (for journal + description)
        detail_items = api_items[:max_detail_fetch]
        bulk_items = api_items[max_detail_fetch:]

        logger.info(
            "[%s] Fetching detail pages for first %d items (concurrency=%d)",
            self.source_name, len(detail_items), concurrency,
        )
        detailed_cfps = await self._fetch_details_concurrent(detail_items, concurrency)
        bulk_cfps = [self._build_basic_cfp(item) for item in bulk_items]

        all_cfps = detailed_cfps + bulk_cfps

        # Deduplicate
        seen: set[str] = set()
        unique = [c for c in all_cfps if not (c.id in seen or seen.add(c.id))]  # type: ignore

        logger.info("[%s] Total unique CFPs: %d", self.source_name, len(unique))
        return unique, ScrapingStatus(
            source_id=self.source_id, source=self.source_name, success=True, count=len(unique)
        )

    # ── API pagination ────────────────────────────────────────────────────────

    async def _fetch_all_api_items(self, api_url: str, page_size: int, max_pages: int) -> list[dict]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        params = {
            "_fields": "id,title,link,meta",
            "per_page": page_size,
            "page": 1,
            "orderby": "date",
            "order": "desc",
        }
        all_items: list[dict] = []

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            # First request to get total
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data)

            total = int(resp.headers.get("X-WP-Total", 0))
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            logger.info("[%s] Total special issues: %d (%d pages)", self.source_name, total, total_pages)

            # Fetch remaining pages concurrently
            if total_pages > 1:
                tasks = [
                    client.get(api_url, params={**params, "page": p})
                    for p in range(2, min(total_pages + 1, max_pages + 1))
                ]
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                for resp in responses:
                    if isinstance(resp, Exception):
                        logger.warning("[%s] Page fetch error: %s", self.source_name, resp)
                        continue
                    if hasattr(resp, "status_code") and resp.status_code == 200:
                        all_items.extend(resp.json())

        return all_items

    # ── Concurrent detail fetching ────────────────────────────────────────────

    async def _fetch_details_concurrent(self, items: list[dict], concurrency: int) -> List[CallForPaper]:
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_one(item: dict) -> CallForPaper:
            async with semaphore:
                try:
                    return await self._fetch_page_cfp(item)
                except Exception as exc:
                    logger.debug("[%s] Detail page error for %s: %s", self.source_name, item.get("link", ""), exc)
                    return self._build_basic_cfp(item)

        results = await asyncio.gather(*[fetch_one(item) for item in items])
        return list(results)

    async def _fetch_page_cfp(self, item: dict) -> CallForPaper:
        link = item.get("link", "")
        title = clean(item.get("title", {}).get("rendered", ""))
        expiry = item.get("meta", {}).get("meta-page-expiry-date", "")

        soup = await self.fetch(link)
        if soup is None:
            return self._build_basic_cfp(item)

        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup
        main_text = clean(main.get_text())

        # Journal name — appears right after "Submit a Manuscript to the Journal"
        journal = "No disponible"
        m = re.search(
            r"Submit a Manuscript to the Journal\s+(.+?)\s+For a Special Issue on",
            main_text, re.S,
        )
        if m:
            journal = clean(m.group(1))
        else:
            # Fallback: find journal link text
            jlink = main.find("a", href=lambda h: h and "tandfonline.com/journals" in h)
            if not jlink:
                jlink = main.find("a", string=re.compile(r"View .+ on Taylor", re.I))
            if jlink:
                txt = clean(jlink.get_text())
                journal = re.sub(r"^View\s+", "", txt, flags=re.I)
                journal = re.sub(r"\s+on Taylor.*$", "", journal, flags=re.I).strip()

        # Deadlines — prefer "Manuscript deadline" over abstract deadline
        deadline = "No disponible"
        ms_match = re.search(r"Manuscript deadline\s+([\d\w\s]+\d{4})", main_text, re.I)
        abs_match = re.search(r"Abstract deadline\s+([\d\w\s]+\d{4})", main_text, re.I)
        if ms_match:
            deadline = clean(ms_match.group(1))
        elif abs_match:
            deadline = clean(abs_match.group(1))
        elif expiry:
            deadline = expiry  # ISO date from meta

        if deadline == "No disponible":
            deadline = extract_date(main_text)

        # Description — first substantive paragraph that isn't editor/author lines
        description = "No disponible"
        desc_paras = [
            clean(p.get_text())
            for p in main.find_all("p")
            if len(clean(p.get_text())) > 100
            and "@" not in p.get_text()  # skip editor contact lines
            and not re.search(r"^[A-Z][a-z]+\s+[A-Z][a-z]+,\s+[A-Z]", p.get_text())  # skip "Name, University"
        ]
        if desc_paras:
            description = self._truncate(desc_paras[0])

        return CallForPaper(
            id=make_id(self.source_name, title),
            title=title,
            source=self.source_name,
            journal=journal,
            deadline=deadline,
            description=description,
            url=link,
        )

    # ── Basic CFP (from API metadata only) ───────────────────────────────────

    def _build_basic_cfp(self, item: dict) -> CallForPaper:
        title = clean(item.get("title", {}).get("rendered", ""))
        link = item.get("link", "No disponible")
        expiry = item.get("meta", {}).get("meta-page-expiry-date", "")
        deadline = expiry if expiry else "No disponible"

        return CallForPaper(
            id=make_id(self.source_name, title),
            title=title,
            source=self.source_name,
            deadline=deadline,
            url=link,
        )
