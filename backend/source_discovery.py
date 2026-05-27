import logging
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from models import Source
from scrapers.base import HEADERS
from scrapers.generic_html import GenericHtmlScraper

logger = logging.getLogger(__name__)

TAYLOR_API = "https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues"

GENERIC_CANDIDATES = [
    {
        "item_selector": "li.app-article-list-row__item",
        "title_selector": "[data-test='link-title'], h2 a, h3 a",
        "url_selector": "[data-test='link-title'], h2 a, h3 a",
        "deadline_selector": "[data-test='end-date']",
        "description_selector": "[data-test='description'], .c-card__summary",
    },
    {
        "item_selector": "article.c-card",
        "title_selector": "[data-test='link-title'], h2 a, h3 a",
        "url_selector": "[data-test='link-title'], h2 a, h3 a",
        "deadline_selector": "[data-test='end-date']",
        "description_selector": "[data-test='description'], .c-card__summary",
    },
    {
        "item_selector": "main article",
        "title_selector": "h2 a, h3 a, a",
        "url_selector": "h2 a, h3 a, a",
        "description_selector": "p",
    },
    {
        "item_selector": "article",
        "title_selector": "h2 a, h3 a, a",
        "url_selector": "h2 a, h3 a, a",
        "description_selector": "p",
    },
    {
        "item_selector": "main h3",
        "title_selector": "a",
        "url_selector": "a",
        "description_selector": "p",
    },
    {
        "item_selector": "main h2",
        "title_selector": "a",
        "url_selector": "a",
        "description_selector": "p",
    },
    {
        "item_selector": "main li",
        "title_selector": "a",
        "url_selector": "a",
    },
]


async def discover_source(name: str, url: str) -> tuple[str, dict]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "taylorandfrancis.com" in host:
        return "taylor_francis", {
            "api_url": TAYLOR_API,
            "page_size": 100,
            "max_pages": 10,
            "max_detail_fetch": 60,
            "concurrency": 8,
        }

    if "apa.org" in host and "calls-for-papers" in path:
        return "apa", {}

    if "sciencedirect.com" in host and "calls-for-papers" in path:
        return "sciencedirect", {}

    if "nature.com" in host and "calls-for-papers" in path:
        return "generic_html", {
            "item_selector": "li.app-article-list-row__item",
            "title_selector": "[data-test='link-title'], h2 a, h3 a",
            "url_selector": "[data-test='link-title'], h2 a, h3 a",
            "deadline_selector": "[data-test='end-date']",
            "description_selector": "[data-test='description'], .c-card__summary",
            "default_journal": name,
        }

    settings = await _discover_generic_html(name, url)
    return "generic_html", settings


async def _discover_generic_html(name: str, url: str) -> dict:
    soup = await _fetch_soup(url)
    if soup is None:
        logger.info("Generic discovery fallback for %s: fetch failed", url)
        return {"default_journal": name}

    best_settings = {"default_journal": name}
    best_score = 0

    for candidate in GENERIC_CANDIDATES:
        settings = {**candidate, "default_journal": name}
        score = _score_candidate(name, url, settings, soup)
        if score > best_score:
            best_score = score
            best_settings = settings

    logger.info("Generic discovery for %s selected score=%d settings=%s", url, best_score, best_settings)
    return best_settings


async def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
    except Exception as exc:
        logger.info("Unable to fetch %s during discovery: %s", url, exc)
        return None


def _score_candidate(name: str, url: str, settings: dict, soup: BeautifulSoup) -> int:
    source = Source(
        id=0,
        name=name,
        scraper_type="generic_html",
        url=url,
        enabled=True,
        settings=settings,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    scraper = GenericHtmlScraper(source=source)
    try:
        cfps = scraper._parse_soup(soup)
    except Exception:
        return 0

    valid = [cfp for cfp in cfps if cfp.title and cfp.url != "No disponible"]
    dated = [cfp for cfp in valid if cfp.deadline != "No disponible"]
    described = [cfp for cfp in valid if cfp.description != "No disponible"]

    return min(len(valid), 30) * 10 + min(len(dated), 20) * 4 + min(len(described), 20)
