import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from models import Search, SearchCreate, SearchUpdate, Source, SourceCreate, SourceUpdate

DB_PATH = Path(__file__).parent / "data" / "call_of_papers.sqlite3"


DEFAULT_SOURCES = [
    SourceCreate(
        name="Taylor & Francis",
        scraper_type="taylor_francis",
        url="https://authorservices.taylorandfrancis.com/call-for-papers/",
        enabled=True,
        settings={
            "api_url": "https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues",
            "page_size": 100,
            "max_pages": 10,
            "max_detail_fetch": 60,
            "concurrency": 8,
        },
    ),
    SourceCreate(
        name="APA",
        scraper_type="apa",
        url="https://www.apa.org/pubs/journals/resources/calls-for-papers",
        enabled=True,
        settings={},
    ),
]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                scraper_type TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_run_at TEXT,
                last_success INTEGER,
                last_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                keywords_text TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_notified_at TEXT,
                last_match_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );
            """
        )
        _seed_defaults(conn)


def list_sources(enabled_only: bool = False) -> list[Source]:
    query = "SELECT * FROM sources"
    params: tuple = ()
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY name COLLATE NOCASE"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_source(row) for row in rows]


def get_source(source_id: int) -> Source | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return _row_to_source(row) if row else None


def create_source(payload: SourceCreate) -> Source:
    now = _now()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sources (
                name, scraper_type, url, enabled, settings_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                _required_scraper_type(payload),
                payload.url.strip(),
                int(payload.enabled),
                json.dumps(payload.settings, ensure_ascii=False),
                now,
                now,
            ),
        )
        source_id = int(cursor.lastrowid)
    source = get_source(source_id)
    if source is None:
        raise RuntimeError("No se pudo recuperar la fuente creada")
    return source


def update_source(source_id: int, payload: SourceUpdate) -> Source | None:
    current = get_source(source_id)
    if current is None:
        return None

    values: dict[str, object] = {}
    if payload.name is not None:
        values["name"] = payload.name.strip()
    if payload.scraper_type is not None:
        values["scraper_type"] = payload.scraper_type.strip()
    if payload.url is not None:
        values["url"] = payload.url.strip()
    if payload.enabled is not None:
        values["enabled"] = int(payload.enabled)
    if payload.settings is not None:
        values["settings_json"] = json.dumps(payload.settings, ensure_ascii=False)

    if values:
        values["updated_at"] = _now()
        set_clause = ", ".join(f"{key} = ?" for key in values)
        params = [*values.values(), source_id]
        with _connect() as conn:
            conn.execute(f"UPDATE sources SET {set_clause} WHERE id = ?", params)

    return get_source(source_id)


def delete_source(source_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return cursor.rowcount > 0


def set_source_enabled(source_id: int, enabled: bool) -> Source | None:
    return update_source(source_id, SourceUpdate(enabled=enabled))


def record_source_run(
    source_id: int,
    *,
    success: bool,
    count: int,
    error: str | None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sources
            SET last_run_at = ?,
                last_success = ?,
                last_count = ?,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_now(), int(success), count, error, _now(), source_id),
        )


def list_searches(enabled_only: bool = False) -> list[Search]:
    query = "SELECT * FROM searches"
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY name COLLATE NOCASE"

    with _connect() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_search(row) for row in rows]


def get_search(search_id: int) -> Search | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    return _row_to_search(row) if row else None


def create_search(payload: SearchCreate) -> Search:
    now = _now()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO searches (
                name, email, keywords_text, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.email.strip(),
                payload.keywords_text.strip(),
                int(payload.enabled),
                now,
                now,
            ),
        )
        search_id = int(cursor.lastrowid)
    search = get_search(search_id)
    if search is None:
        raise RuntimeError("No se pudo recuperar la búsqueda creada")
    return search


def update_search(search_id: int, payload: SearchUpdate) -> Search | None:
    current = get_search(search_id)
    if current is None:
        return None

    values: dict[str, object] = {}
    if payload.name is not None:
        values["name"] = payload.name.strip()
    if payload.email is not None:
        values["email"] = payload.email.strip()
    if payload.keywords_text is not None:
        values["keywords_text"] = payload.keywords_text.strip()
    if payload.enabled is not None:
        values["enabled"] = int(payload.enabled)

    if values:
        values["updated_at"] = _now()
        set_clause = ", ".join(f"{key} = ?" for key in values)
        params = [*values.values(), search_id]
        with _connect() as conn:
            conn.execute(f"UPDATE searches SET {set_clause} WHERE id = ?", params)

    return get_search(search_id)


def delete_search(search_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        return cursor.rowcount > 0


def set_search_enabled(search_id: int, enabled: bool) -> Search | None:
    return update_search(search_id, SearchUpdate(enabled=enabled))


def record_search_run(
    search_id: int,
    *,
    match_count: int,
    notified: bool,
    error: str | None,
) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE searches
            SET last_checked_at = ?,
                last_notified_at = CASE WHEN ? THEN ? ELSE last_notified_at END,
                last_match_count = ?,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, int(notified), now, match_count, error, now, search_id),
        )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _seed_defaults(conn: sqlite3.Connection) -> None:
    seeded = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'default_sources_seeded'"
    ).fetchone()
    if seeded:
        return

    for source in DEFAULT_SOURCES:
        _insert_source(conn, source)

    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES ('default_sources_seeded', '1')"
    )


def _insert_source(conn: sqlite3.Connection, source: SourceCreate) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO sources (
            name, scraper_type, url, enabled, settings_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.name,
            _required_scraper_type(source),
            source.url,
            int(source.enabled),
            json.dumps(source.settings, ensure_ascii=False),
            now,
            now,
        ),
    )


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source(
        id=int(row["id"]),
        name=row["name"],
        scraper_type=row["scraper_type"],
        url=row["url"],
        enabled=bool(row["enabled"]),
        settings=_load_settings(row["settings_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_run_at=_parse_datetime(row["last_run_at"]),
        last_success=_parse_bool(row["last_success"]),
        last_count=int(row["last_count"] or 0),
        last_error=row["last_error"],
    )


def _row_to_search(row: sqlite3.Row) -> Search:
    return Search(
        id=int(row["id"]),
        name=row["name"],
        email=row["email"],
        keywords_text=row["keywords_text"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_checked_at=_parse_datetime(row["last_checked_at"]),
        last_notified_at=_parse_datetime(row["last_notified_at"]),
        last_match_count=int(row["last_match_count"] or 0),
        last_error=row["last_error"],
    )


def _load_settings(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _required_scraper_type(source: SourceCreate) -> str:
    if not source.scraper_type:
        raise ValueError("scraper_type es obligatorio para persistir una fuente")
    return source.scraper_type.strip()
