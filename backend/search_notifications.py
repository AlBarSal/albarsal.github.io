import asyncio
import html
import logging
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from models import CallForPaper, Search

logger = logging.getLogger(__name__)


@dataclass
class SearchMatch:
    keyword: str
    cfp: CallForPaper


@dataclass
class SearchNotificationResult:
    search_id: int
    search_name: str
    match_count: int
    notified: bool
    error: str | None = None


async def notify_searches(
    searches: list[Search], cfps: list[CallForPaper]
) -> list[SearchNotificationResult]:
    results: list[SearchNotificationResult] = []

    for search in searches:
        matches = find_search_matches(search, cfps)
        if not matches:
            results.append(
                SearchNotificationResult(
                    search_id=search.id,
                    search_name=search.name,
                    match_count=0,
                    notified=False,
                )
            )
            continue

        try:
            await send_search_email(search, matches)
            results.append(
                SearchNotificationResult(
                    search_id=search.id,
                    search_name=search.name,
                    match_count=len(matches),
                    notified=True,
                )
            )
        except Exception as exc:
            logger.error("Unable to notify search %s: %s", search.name, exc)
            results.append(
                SearchNotificationResult(
                    search_id=search.id,
                    search_name=search.name,
                    match_count=len(matches),
                    notified=False,
                    error=str(exc),
                )
            )

    return results


def find_search_matches(search: Search, cfps: list[CallForPaper]) -> list[SearchMatch]:
    keywords = parse_keywords(search.keywords_text)
    matches: list[SearchMatch] = []

    for keyword in keywords:
        keyword_lower = keyword.lower()
        for cfp in cfps:
            if keyword_lower in _searchable_text(cfp):
                matches.append(SearchMatch(keyword=keyword, cfp=cfp))

    return matches


def parse_keywords(text: str) -> list[str]:
    has_explicit_separator = bool(re.search(r"[,;\n\r]", text))
    raw_parts = re.split(r"[,;\n\r]+", text) if has_explicit_separator else text.split()
    seen: set[str] = set()
    keywords: list[str] = []

    for part in raw_parts:
        keyword = re.sub(r"\s+", " ", part).strip()
        key = keyword.lower()
        if keyword and key not in seen:
            seen.add(key)
            keywords.append(keyword)

    return keywords


async def send_search_email(search: Search, matches: list[SearchMatch]) -> None:
    message = _build_message(search, matches)
    await asyncio.to_thread(_send_message, message)


def _build_message(search: Search, matches: list[SearchMatch]) -> EmailMessage:
    config = _smtp_config()
    sender = formataddr((config["from_name"], config["from_email"]))

    message = EmailMessage()
    message["Subject"] = f"Call for Papers: coincidencias para {search.name}"
    message["From"] = sender
    message["To"] = search.email
    message.set_content(_build_text_body(search, matches))
    message.add_alternative(_build_html_body(search, matches), subtype="html")
    return message


def _send_message(message: EmailMessage) -> None:
    config = _smtp_config()
    host = config["host"]
    port = int(config["port"])
    timeout = float(config["timeout"])

    if config["ssl"]:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
            _login_and_send(smtp, config, message)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if config["tls"]:
            smtp.starttls()
        _login_and_send(smtp, config, message)


def _login_and_send(smtp: smtplib.SMTP, config: dict, message: EmailMessage) -> None:
    if config["username"] and config["password"]:
        smtp.login(config["username"], config["password"])
    smtp.send_message(message)


def _smtp_config() -> dict:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM", "").strip() or username

    if not host or not from_email:
        raise RuntimeError(
            "SMTP no configurado: defina SMTP_HOST, SMTP_PORT y SMTP_FROM"
        )

    return {
        "host": host,
        "port": os.getenv("SMTP_PORT", "587").strip(),
        "username": username,
        "password": password,
        "from_email": from_email,
        "from_name": os.getenv("SMTP_FROM_NAME", "Call for Papers Explorer").strip(),
        "tls": _env_bool("SMTP_TLS", True),
        "ssl": _env_bool("SMTP_SSL", False),
        "timeout": os.getenv("SMTP_TIMEOUT", "20").strip(),
    }


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _searchable_text(cfp: CallForPaper) -> str:
    parts = [cfp.title, cfp.journal, cfp.description]
    return " ".join(part for part in parts if part and part != "No disponible").lower()


def _build_text_body(search: Search, matches: list[SearchMatch]) -> str:
    lines = [
        f"Búsqueda: {search.name}",
        f"Coincidencias: {len(matches)}",
        "",
    ]

    for match in matches:
        cfp = match.cfp
        lines.extend(
            [
                f"- [{match.keyword}] {cfp.title}",
                f"  Fuente: {cfp.source}",
                f"  Revista: {cfp.journal}",
                f"  Fecha límite: {cfp.deadline}",
                f"  URL: {cfp.url}",
                "",
            ]
        )

    return "\n".join(lines)


def _build_html_body(search: Search, matches: list[SearchMatch]) -> str:
    rows = "\n".join(_build_match_row(match) for match in matches)
    return f"""<!doctype html>
<html lang="es">
  <body style="margin:0;padding:24px;background:#f3f4f6;font-family:Arial,sans-serif;color:#111827;">
    <main style="max-width:760px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      <header style="padding:20px 24px;border-bottom:1px solid #e5e7eb;">
        <h1 style="margin:0;font-size:20px;line-height:1.3;">Coincidencias encontradas</h1>
        <p style="margin:8px 0 0;color:#6b7280;font-size:14px;">Búsqueda: {html.escape(search.name)} · {len(matches)} coincidencia{"s" if len(matches) != 1 else ""}</p>
      </header>
      <section style="padding:16px 24px;">
        {rows}
      </section>
    </main>
  </body>
</html>"""


def _build_match_row(match: SearchMatch) -> str:
    cfp = match.cfp
    url = "" if cfp.url == "No disponible" else cfp.url
    link = (
        f'<a href="{html.escape(url)}" style="color:#2563eb;text-decoration:none;">Ver convocatoria</a>'
        if url
        else '<span style="color:#6b7280;">URL no disponible</span>'
    )

    return f"""
        <article style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
          <div style="font-size:12px;font-weight:700;color:#1d4ed8;margin-bottom:8px;">{html.escape(match.keyword)}</div>
          <h2 style="margin:0 0 8px;font-size:16px;line-height:1.35;">{html.escape(cfp.title)}</h2>
          <p style="margin:0 0 4px;color:#374151;font-size:13px;"><strong>Fuente:</strong> {html.escape(cfp.source)}</p>
          <p style="margin:0 0 4px;color:#374151;font-size:13px;"><strong>Revista:</strong> {html.escape(cfp.journal)}</p>
          <p style="margin:0 0 10px;color:#374151;font-size:13px;"><strong>Fecha límite:</strong> {html.escape(cfp.deadline)}</p>
          <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.5;">{html.escape(cfp.description)}</p>
          <p style="margin:12px 0 0;font-size:13px;">{link}</p>
        </article>"""
