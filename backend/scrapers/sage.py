import logging
import re
from typing import List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, make_id

logger = logging.getLogger(__name__)

URL = "https://journals.sagepub.com/open-call-for-papers"
_READER_PREFIX = "https://r.jina.ai/http://"
_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_DEADLINE_RE = re.compile(r"Submission deadline\s*:?\s*\**([^*\[\n]+)", re.I)


class SageScraper(BaseScraper):
    source_name = "Sage Journals"
    url = URL

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        logger.info("[%s] Starting reader scrape of %s", self.source_name, self.url)
        try:
            markdown = await self._fetch_reader_markdown()
            cfps = self._parse_reader_markdown(markdown)
        except Exception as exc:
            logger.error("[%s] Reader scrape failed: %s", self.source_name, exc)
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error=f"No se pudo acceder a Sage Journals: {exc}",
            )

        if not cfps:
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error="No se encontraron convocatorias en Sage Journals",
            )

        seen: set[str] = set()
        unique = [cfp for cfp in cfps if not (cfp.url in seen or seen.add(cfp.url))]  # type: ignore
        return unique, ScrapingStatus(
            source_id=self.source_id,
            source=self.source_name,
            success=True,
            count=len(unique),
        )

    async def _fetch_reader_markdown(self) -> str:
        reader_url = f"{_READER_PREFIX}{self.url}"
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(reader_url)
            response.raise_for_status()
            text = response.text
        if "Just a moment" in text or "Target URL returned error 403" in text:
            raise RuntimeError("Sage bloqueó el acceso directo y reader devolvió bloqueo")
        return text

    def _parse_reader_markdown(self, markdown: str) -> List[CallForPaper]:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        start_index = 0
        for index, line in enumerate(lines):
            if line.startswith("### "):
                start_index = index
                break

        current_journal = "No disponible"
        pending: dict | None = None
        cfps: List[CallForPaper] = []

        def flush(deadline: str = "") -> None:
            nonlocal pending
            if not pending:
                return
            title = pending["title"]
            cfps.append(
                CallForPaper(
                    id=make_id(self.source_name, title),
                    title=title,
                    source=self.source_name,
                    journal=pending["journal"],
                    deadline=deadline or pending.get("deadline") or "No disponible",
                    description="No disponible",
                    url=pending["url"],
                )
            )
            pending = None

        for line in lines[start_index:]:
            if line.startswith("### "):
                flush()
                continue

            links = [
                (self._clean_markdown(label), self._strip_tracking(url))
                for label, url in _LINK_RE.findall(line)
            ]
            deadline = self._extract_deadline(line)

            for title, url in links:
                if not title or title.lower().startswith("image "):
                    continue
                if "/home/" in url and not self._is_noise(title, url):
                    current_journal = title
                    continue
                if self._is_noise(title, url) or not self._is_call(title, url):
                    continue

                if pending:
                    flush(deadline if deadline else "")
                    deadline = ""
                pending = {
                    "title": title,
                    "url": url,
                    "journal": current_journal,
                    "deadline": "No disponible",
                }

            if deadline and pending:
                flush(deadline)

        flush()
        return cfps

    def _extract_deadline(self, line: str) -> str:
        match = _DEADLINE_RE.search(line)
        if not match:
            return ""
        return self._clean_markdown(match.group(1)).strip(": ") or "No disponible"

    def _is_call(self, title: str, url: str) -> bool:
        text = f"{title} {url}".lower()
        return any(
            token in text
            for token in ("call", "special issue", "cfp", "author-instructions", "special-issues", "why-publish")
        )

    def _is_noise(self, title: str, url: str) -> bool:
        text = f"{title} {url}".lower()
        return any(
            token in text
            for token in (
                "skip",
                "search",
                "login",
                "cart",
                "profile",
                "view access",
                "advanced search",
                "all disciplines",
                "special collections",
                "frequently asked",
            )
        )

    def _clean_markdown(self, text: str) -> str:
        text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
        text = re.sub(r"[*_`]+", "", text)
        return clean(text)

    def _strip_tracking(self, url: str) -> str:
        parts = urlsplit(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.startswith(("_gl", "_ga"))
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
