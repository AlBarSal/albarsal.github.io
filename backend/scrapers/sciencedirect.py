import logging
import os
from typing import List, Tuple

import httpx

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, make_id

logger = logging.getLogger(__name__)

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
BROWSE_URL = "https://www.sciencedirect.com/browse/calls-for-papers"

_CFP_SUBTYPES = {"ed", "no", "le", "sh"}  # Editorial, Note, Letter, Short Survey
_DEFAULT_COUNT = 200
_DEFAULT_MONTHS = 12
_PAGE_SIZE = 25  # Scopus free-tier API key limit per request


class ScienceDirectScraper(BaseScraper):
    """
    Scrapes Calls for Papers indexed in Scopus (Elsevier API).

    The ScienceDirect browse page is blocked by Elsevier's CDN (Akamai Bot Manager)
    for all automated access, including Playwright with stealth settings. The Scopus
    Search API is the only available programmatic source for Elsevier CFP data with
    a standard API key.

    Requires API_KEY_ELSEVIER in the .env file.
    """

    source_name = "ScienceDirect"
    url = BROWSE_URL

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        api_key = os.environ.get("API_KEY_ELSEVIER") or self.settings.get("api_key", "")
        if not api_key:
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error="API_KEY_ELSEVIER no configurada en .env",
            )

        count = int(self.settings.get("count", _DEFAULT_COUNT))
        months = int(self.settings.get("months", _DEFAULT_MONTHS))

        logger.info(
            "[%s] Iniciando scrape via Scopus API (últimos %d meses, máx %d)",
            self.source_name, months, count,
        )

        try:
            cfps = await self._scrape_scopus(api_key, count, months)
            logger.info("[%s] Scopus encontró %d CFPs", self.source_name, len(cfps))
            return cfps, ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=True,
                count=len(cfps),
            )
        except RuntimeError as exc:
            logger.warning("[%s] %s", self.source_name, exc)
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error=str(exc),
            )
        except Exception as exc:
            logger.error("[%s] Error Scopus API: %s", self.source_name, exc)
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error=f"Error Scopus API: {exc}",
            )

    async def _scrape_scopus(self, api_key: str, max_count: int, months: int) -> List[CallForPaper]:
        import datetime
        since_year = (datetime.date.today() - datetime.timedelta(days=months * 30)).year - 1

        # Construct URL as a string with literal parentheses preserved.
        # httpx respects RFC 3986 sub-delimiters (including "()" and "+") in pre-built URLs;
        # using params=dict would percent-encode them (%28/%29) which the API rejects.
        # Double-quoted phrases are also rejected by the free API key — keyword AND is enough.
        _fields = "dc:title,prism:publicationName,prism:doi,prism:coverDate,subtype,link"
        _base = (
            f"{SCOPUS_SEARCH_URL}"
            f"?query=TITLE(call+for+papers)+AND+PUBYEAR+AFT+{since_year}"
            f"&sort=-coverDate&field={_fields}&apiKey={api_key}"
        )

        cfps: List[CallForPaper] = []
        start = 0
        fetched_total = 0

        async with httpx.AsyncClient(timeout=30) as client:
            while fetched_total < max_count:
                page_size = min(_PAGE_SIZE, max_count - fetched_total)
                url = f"{_base}&start={start}&count={page_size}"

                resp = await client.get(url, headers={"Accept": "application/json"})

                if resp.status_code == 401:
                    raise RuntimeError(
                        "API key no autorizada para Scopus Search. "
                        "Verifica API_KEY_ELSEVIER en .env."
                    )
                resp.raise_for_status()

                sr = resp.json().get("search-results", {})
                entries = sr.get("entry", [])
                if not entries:
                    break

                for entry in entries:
                    cfp = self._entry_to_cfp(entry)
                    if cfp:
                        cfps.append(cfp)

                fetched_total += len(entries)
                total_available = int(sr.get("opensearch:totalResults", 0))
                start += len(entries)
                if start >= total_available:
                    break

        # Deduplicate by id
        seen: set[str] = set()
        return [c for c in cfps if not (c.id in seen or seen.add(c.id))]  # type: ignore

    def _entry_to_cfp(self, entry: dict) -> CallForPaper | None:
        title = clean(entry.get("dc:title", ""))
        if not title or len(title) < 10:
            return None

        subtype = entry.get("subtype", "")
        if subtype not in _CFP_SUBTYPES:
            return None

        # Make sure title is CFP-related (Scopus may return edge cases)
        title_lower = title.lower()
        if not any(kw in title_lower for kw in ("call for papers", "call for submissions", "special issue")):
            return None

        journal = clean(entry.get("prism:publicationName", "")) or "No disponible"

        doi = entry.get("prism:doi", "")
        url = f"https://doi.org/{doi}" if doi else self._scopus_web_link(entry)

        return CallForPaper(
            id=make_id(self.source_name, title),
            title=title,
            source=self.source_name,
            journal=journal,
            deadline="No disponible",
            url=url or "No disponible",
        )

    def _scopus_web_link(self, entry: dict) -> str:
        for lnk in entry.get("link", []):
            if lnk.get("@ref") == "scopus":
                return lnk.get("@href", "")
        return ""
