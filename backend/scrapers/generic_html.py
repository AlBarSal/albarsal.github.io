import logging
import re
from copy import copy
from typing import List, Tuple

from bs4 import BeautifulSoup, Tag

from models import CallForPaper, ScrapingStatus
from .base import BaseScraper, clean, extract_date, make_id

logger = logging.getLogger(__name__)


class GenericHtmlScraper(BaseScraper):
    source_name = "HTML genérico"
    url = ""

    async def scrape(self) -> Tuple[List[CallForPaper], ScrapingStatus]:
        if not self.url:
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error="La fuente no tiene URL",
            )

        logger.info("[%s] Starting generic HTML scrape of %s", self.source_name, self.url)
        soup = await self.fetch(self.url)
        if soup is None:
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error="No se pudo acceder a la página",
            )

        try:
            cfps = self._parse_soup(soup)
        except Exception as exc:
            logger.error("[%s] Generic HTML parse error: %s", self.source_name, exc)
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error=f"Error al parsear HTML: {exc}",
            )

        if not cfps:
            return [], ScrapingStatus(
                source_id=self.source_id,
                source=self.source_name,
                success=False,
                count=0,
                error="No se encontraron convocatorias con la configuración actual",
            )

        seen: set[str] = set()
        unique = [c for c in cfps if not (c.id in seen or seen.add(c.id))]  # type: ignore
        return unique, ScrapingStatus(
            source_id=self.source_id,
            source=self.source_name,
            success=True,
            count=len(unique),
        )

    def _parse_soup(self, soup: BeautifulSoup) -> List[CallForPaper]:
        item_selector = self._setting("item_selector")
        if item_selector:
            return self._parse_configured_items(soup, item_selector)

        return (
            self._strategy_list_items(soup)
            or self._strategy_headings(soup)
            or self._strategy_links(soup)
        )

    def _parse_configured_items(self, soup: BeautifulSoup, item_selector: str) -> List[CallForPaper]:
        rows = soup.select(item_selector)
        results = []
        for row in rows:
            cfp = self._parse_row(row)
            if cfp:
                results.append(cfp)
        return results

    def _strategy_list_items(self, soup: BeautifulSoup) -> List[CallForPaper]:
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup
        results = []
        for row in main.find_all("li"):
            cfp = self._parse_row(row)
            if cfp:
                results.append(cfp)
        return results[:100]

    def _strategy_headings(self, soup: BeautifulSoup) -> List[CallForPaper]:
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup
        results = []
        for heading in main.find_all(["h2", "h3", "h4"]):
            link = heading.find("a", href=True)
            if not link:
                continue
            title = clean(heading.get_text())
            if len(title) < 8:
                continue
            parent = heading.parent if isinstance(heading.parent, Tag) else heading
            results.append(self._build_cfp(title, link["href"], parent))
        return results[:100]

    def _strategy_links(self, soup: BeautifulSoup) -> List[CallForPaper]:
        results = []
        for link in soup.find_all("a", href=True):
            title = clean(link.get_text())
            href = link["href"]
            if len(title) < 8:
                continue
            if not self._looks_like_cfp(title, href):
                continue
            parent = link.parent if isinstance(link.parent, Tag) else link
            results.append(self._build_cfp(title, href, parent))
        return results[:100]

    def _parse_row(self, row: Tag) -> CallForPaper | None:
        row = self._context_for_heading(row)
        title = self._text_from(row, self._setting("title_selector"))
        link = self._link_from(row, self._setting("url_selector"))

        if not title:
            link_tag = row.find("a", href=True)
            if link_tag:
                title = clean(link_tag.get_text())
                link = link or link_tag["href"]

        if not title or len(title) < 8:
            return None

        return self._build_cfp(title, link or "", row)

    def _build_cfp(self, title: str, href: str, context: Tag) -> CallForPaper:
        full_text = clean(context.get_text())
        journal = (
            self._text_from(context, self._setting("journal_selector"))
            or self._setting("default_journal")
            or "No disponible"
        )
        deadline_text = self._text_from(context, self._setting("deadline_selector"))
        deadline = self._normalize_deadline(deadline_text) if deadline_text else extract_date(full_text)
        description = self._text_from(context, self._setting("description_selector"))

        if not description:
            description = full_text.replace(title, "", 1).strip()

        return CallForPaper(
            id=make_id(self.source_name, title),
            title=title,
            source=self.source_name,
            journal=journal,
            deadline=deadline,
            description=self._truncate(description) if description else "No disponible",
            url=self._make_absolute(href, self.url),
        )

    def _text_from(self, row: Tag, selector: str | None) -> str:
        if not selector:
            return ""
        found = row.select_one(selector)
        return clean(found.get_text()) if found else ""

    def _link_from(self, row: Tag, selector: str | None) -> str:
        if not selector:
            return ""
        found = row.select_one(selector)
        if not found:
            return ""
        if found.name == "a" and found.has_attr("href"):
            return str(found["href"])
        nested = found.find("a", href=True)
        return str(nested["href"]) if nested else ""

    def _context_for_heading(self, row: Tag) -> Tag:
        if row.name not in {"h2", "h3", "h4"}:
            return row

        title = clean(row.get_text())
        parent = row.parent if isinstance(row.parent, Tag) else None
        if parent and parent.name not in {"main", "body", "html"}:
            parent_text = clean(parent.get_text())
            if len(parent_text) > len(title) + 40 and "deadline" in parent_text.lower():
                return parent

        soup = BeautifulSoup("<div></div>", "lxml")
        wrapper = soup.div
        wrapper.append(copy(row))

        for sibling in row.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4"}:
                break
            wrapper.append(copy(sibling))
            if len(clean(wrapper.get_text())) > 800:
                break

        return wrapper

    def _setting(self, key: str) -> str | None:
        value = self.settings.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def _normalize_deadline(self, text: str) -> str:
        text = clean(text)
        text = re.sub(r"^(submission\s+)?deadline\s*:?\s*", "", text, flags=re.I)
        return text or "No disponible"

    def _looks_like_cfp(self, title: str, href: str) -> bool:
        text = f"{title} {href}".lower()
        return any(token in text for token in ("call", "paper", "special issue", "submit", "submission"))
