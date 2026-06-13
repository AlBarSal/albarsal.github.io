import logging
import re
from typing import List, Tuple
from urllib.parse import urljoin
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, make_id

logger = logging.getLogger(__name__)

URL = "https://journals.sagepub.com/open-call-for-papers"
_READER_PREFIX = "https://r.jina.ai/http://"
_ARCHIVE_AVAILABLE_URL = "https://archive.org/wayback/available"
_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_DEADLINE_RE = re.compile(r"Submission deadline\s*:?\s*\**([^*\[\n]+)", re.I)
_WAYBACK_URL_RE = re.compile(
    r"(?:https?://web\.archive\.org)?/web/\d+(?:[a-z]{2}_)?/(https?://.+)"
)


class SageScraper(BaseScraper):
    source_name = "Sage Journals"
    url = URL

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        logger.info("[%s] Starting scrape of %s", self.source_name, self.url)
        failures: list[str] = []

        soup = await self._fetch_live_soup()
        if soup is not None:
            cfps = self._parse_html_soup(soup)
            if cfps:
                return self._success(cfps)
            failures.append("HTML directo sin convocatorias parseables")

        try:
            markdown = await self._fetch_reader_markdown()
            cfps = self._parse_reader_markdown(markdown)
            if cfps:
                return self._success(cfps)
            failures.append("reader sin convocatorias parseables")
        except Exception as exc:
            logger.warning("[%s] Reader scrape failed: %s", self.source_name, exc)
            failures.append(f"reader bloqueado: {exc}")

        try:
            archive_soup = await self._fetch_archive_soup()
            cfps = self._parse_html_soup(archive_soup)
            if cfps:
                logger.info("[%s] Wayback fallback found %d CFPs", self.source_name, len(cfps))
                return self._success(cfps)
            failures.append("snapshot de Wayback sin convocatorias parseables")
        except Exception as exc:
            logger.warning("[%s] Wayback fallback failed: %s", self.source_name, exc)
            failures.append(f"Wayback no disponible: {exc}")

        error = " ; ".join(failures) if failures else "No se encontraron convocatorias en Sage Journals"
        return [], ScrapingStatus(
            source_id=self.source_id,
            source=self.source_name,
            success=False,
            count=0,
            error=f"No se pudo acceder a Sage Journals: {error}",
        )

    def _success(self, cfps: List[CallForPaper]) -> Tuple[List[CallForPaper], ScrapingStatus]:
        seen: set[str] = set()
        unique = [cfp for cfp in cfps if not (cfp.url in seen or seen.add(cfp.url))]  # type: ignore
        return unique, ScrapingStatus(
            source_id=self.source_id,
            source=self.source_name,
            success=True,
            count=len(unique),
        )

    async def _fetch_live_soup(self) -> BeautifulSoup | None:
        soup = await self.fetch(self.url)
        if soup is None:
            return None
        text = clean(soup.get_text(" ", strip=True))
        if self._looks_blocked(text):
            logger.info("[%s] Direct HTML blocked by Cloudflare", self.source_name)
            return None
        return soup

    async def _fetch_reader_markdown(self) -> str:
        reader_url = f"{_READER_PREFIX}{self.url}"
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(reader_url)
            response.raise_for_status()
            text = response.text
        if "Just a moment" in text or "Target URL returned error 403" in text:
            raise RuntimeError("Sage bloqueó el acceso directo y reader devolvió bloqueo")
        return text

    async def _fetch_archive_soup(self) -> BeautifulSoup:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                _ARCHIVE_AVAILABLE_URL,
                params={"url": self.url},
            )
            response.raise_for_status()
            payload = response.json()

            snapshot = payload.get("archived_snapshots", {}).get("closest", {})
            if not snapshot.get("available") or str(snapshot.get("status")) != "200":
                raise RuntimeError("Wayback no tiene snapshot utilizable")

            snapshot_url = str(snapshot.get("url", "")).strip()
            if not snapshot_url:
                raise RuntimeError("Wayback no devolvió URL de snapshot")

            archived = await client.get(snapshot_url)
            archived.raise_for_status()

        soup = BeautifulSoup(archived.text, "lxml")
        text = clean(soup.get_text(" ", strip=True))
        if self._looks_blocked(text):
            raise RuntimeError("Wayback devolvió una página de bloqueo")
        return soup

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
                    id=self._cfp_id(pending["journal"], title, pending["url"]),
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

    def _parse_html_soup(self, soup: BeautifulSoup) -> List[CallForPaper]:
        content_root = self._find_content_root(soup)
        if content_root is None:
            return []

        cfps: List[CallForPaper] = []
        for heading in content_root.find_all("h3"):
            section_title = clean(heading.get_text(" ", strip=True))
            if not section_title:
                continue

            container = heading.find_next_sibling("div")
            if container is None:
                continue

            current_journal = "No disponible"
            fallback_journal = ""
            pending: dict | None = None
            context_parts: list[str] = []

            def flush() -> None:
                nonlocal pending, context_parts
                if pending is None:
                    return
                context_text = clean(" ".join(context_parts))
                deadline = self._extract_deadline_from_text(context_text)
                description = self._build_description(context_text, deadline)
                cfps.append(
                    CallForPaper(
                        id=self._cfp_id(pending["journal"], pending["title"], pending["url"]),
                        title=pending["title"],
                        source=self.source_name,
                        journal=pending["journal"],
                        deadline=deadline,
                        description=description,
                        url=pending["url"],
                    )
                )
                pending = None
                context_parts = []

            for token in self._html_tokens(container):
                kind = token["kind"]
                text = token["text"]
                if kind == "link":
                    href = token["href"]
                    if token["is_external"]:
                        if pending and pending["url"] == href and not context_parts:
                            pending["title"] = clean(f"{pending['title']} {text}")
                            continue
                        flush()
                        journal = current_journal if current_journal != "No disponible" else fallback_journal
                        pending = {
                            "title": text,
                            "url": href,
                            "journal": journal or "No disponible",
                        }
                        continue

                    flush()
                    current_journal = text
                    fallback_journal = text
                    continue

                if kind == "text":
                    if pending is not None:
                        context_parts.append(text)
                    elif self._looks_like_journal(text):
                        fallback_journal = text

            flush()

        return cfps

    def _extract_deadline(self, line: str) -> str:
        match = _DEADLINE_RE.search(line)
        if not match:
            return ""
        return self._clean_markdown(match.group(1)).strip(": ") or "No disponible"

    def _extract_deadline_from_text(self, text: str) -> str:
        if not text:
            return "No disponible"

        matches = re.findall(
            r"(full manuscript submission deadline|full paper submission deadline|extended abstract submission deadline|abstract submission deadline|proposal submission deadline|deadline for abstract submissions|abstract deadline|submission deadline|deadline)\s*:?\s*([^.]+?)(?=(?:full manuscript submission deadline|full paper submission deadline|extended abstract submission deadline|abstract submission deadline|proposal submission deadline|deadline for abstract submissions|abstract deadline|submission deadline|deadline|final publication|guest editor|$))",
            text,
            flags=re.I,
        )
        if matches:
            _, best_value = max(matches, key=lambda item: self._deadline_priority(item[0]))
            deadline = clean(best_value).strip(": ")
            if deadline:
                return deadline
        return "No disponible"

    def _build_description(self, text: str, deadline: str) -> str:
        if not text:
            return "No disponible"

        description = re.sub(
            r"(?:full manuscript submission deadline|full paper submission deadline|extended abstract submission deadline|abstract submission deadline|proposal submission deadline|deadline for abstract submissions|abstract deadline|submission deadline|deadline)\s*:?\s*[^.]+",
            "",
            text,
            flags=re.I,
        )
        description = clean(description)
        if len(description) < 20:
            return "No disponible"
        if description == deadline or not description:
            return "No disponible"
        return description

    def _find_content_root(self, soup: BeautifulSoup) -> Tag | None:
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body
        if main is None:
            return None

        browse_heading = main.find(
            ["h2", "h3"],
            string=lambda value: value and "Browse the Open Call for Papers" in value,
        )
        if browse_heading is None:
            return main

        parent = browse_heading.parent
        return parent if isinstance(parent, Tag) else main

    def _html_tokens(self, node: Tag) -> list[dict[str, object]]:
        tokens: list[dict[str, object]] = []

        def walk(current: Tag) -> None:
            for child in current.children:
                if isinstance(child, NavigableString):
                    text = clean(str(child))
                    if text:
                        tokens.append({"kind": "text", "text": text})
                    continue

                if not isinstance(child, Tag):
                    continue

                if child.name == "br":
                    continue

                if child.name == "a":
                    text = clean(child.get_text(" ", strip=True))
                    href = self._normalize_href(str(child.get("href", "")))
                    if text and href:
                        tokens.append(
                            {
                                "kind": "link",
                                "text": text,
                                "href": href,
                                "is_external": "external-link" in child.get("class", []),
                            }
                        )
                    continue

                walk(child)

        walk(node)
        return tokens

    def _normalize_href(self, href: str) -> str:
        href = href.strip()
        if not href:
            return ""
        match = _WAYBACK_URL_RE.match(href)
        if match:
            return self._strip_tracking(match.group(1))
        if href.startswith("/web/"):
            match = _WAYBACK_URL_RE.match(urljoin("https://web.archive.org", href))
            if match:
                return self._strip_tracking(match.group(1))
        return self._strip_tracking(self._make_absolute(href, self.url))

    def _looks_blocked(self, text: str) -> bool:
        lowered = text.lower()
        return (
            "just a moment" in lowered
            or "security verification" in lowered
            or "enable javascript and cookies to continue" in lowered
            or "target url returned error 403" in lowered
        )

    def _looks_like_journal(self, text: str) -> bool:
        lowered = text.lower()
        if len(text) > 160:
            return False
        if "deadline" in lowered or "publication" in lowered:
            return False
        if "this section will be updated" in lowered:
            return False
        return bool(re.search(r"[A-Za-z]", text))

    def _deadline_priority(self, label: str) -> int:
        lowered = label.lower()
        if "full manuscript" in lowered or "full paper" in lowered:
            return 5
        if lowered == "submission deadline" or lowered == "deadline":
            return 4
        if "extended abstract" in lowered:
            return 3
        if "abstract" in lowered:
            return 2
        if "proposal" in lowered:
            return 1
        return 0

    def _cfp_id(self, journal: str, title: str, url: str) -> str:
        return make_id(self.source_name, f"{journal}|{title}|{url}")

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
