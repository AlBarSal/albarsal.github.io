import hashlib
import re
import logging
from abc import ABC, abstractmethod
from typing import List, Tuple

import httpx
from bs4 import BeautifulSoup

from models import CallForPaper, ScrapingStatus, Source

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

_DATE_PATTERNS = [
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
]

_DEADLINE_KEYWORDS = [
    "submission deadline",
    "deadline",
    "closing date",
    "closes",
    "submit by",
    "due by",
    "due date",
    "submissions due",
    "papers due",
]


def extract_date(text: str) -> str:
    """Search for a date near deadline-related keywords, then anywhere in text."""
    text_lower = text.lower()
    for keyword in _DEADLINE_KEYWORDS:
        idx = text_lower.find(keyword)
        if idx >= 0:
            snippet = text[idx : idx + 120]
            for pattern in _DATE_PATTERNS:
                m = re.search(pattern, snippet, re.IGNORECASE)
                if m:
                    return m.group(0)
    for pattern in _DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return "No disponible"


def make_id(source: str, title: str) -> str:
    return hashlib.md5(f"{source}:{title.strip().lower()}".encode()).hexdigest()


def clean(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split())


class BaseScraper(ABC):
    source_name: str
    url: str

    def __init__(self, source: Source | None = None):
        self.source_id = source.id if source else None
        self.settings = source.settings if source else {}
        if source:
            self.source_name = source.name
            self.url = source.url

    async def fetch(self, url: str) -> BeautifulSoup | None:
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=30.0
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                logger.info(
                    "[%s] GET %s → %s (%d bytes)",
                    self.source_name,
                    url,
                    resp.status_code,
                    len(resp.content),
                )
                return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.error("[%s] Error fetching %s: %s", self.source_name, url, exc)
            return None

    @abstractmethod
    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        ...

    def _make_absolute(self, href: str, base: str) -> str:
        if not href:
            return "No disponible"
        if href.startswith("http"):
            return href
        from urllib.parse import urljoin
        return urljoin(base, href)

    def _truncate(self, text: str, limit: int = 350) -> str:
        if len(text) > limit:
            return text[:limit].rsplit(" ", 1)[0] + "…"
        return text
