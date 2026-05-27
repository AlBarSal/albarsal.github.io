import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from database import (
    create_search as create_search_record,
    create_source as create_source_record,
    delete_search as delete_search_record,
    delete_source as delete_source_record,
    get_search,
    get_source,
    init_db,
    list_searches,
    list_sources,
    record_search_run,
    record_source_run,
    set_search_enabled,
    set_source_enabled,
    update_search as update_search_record,
    update_source as update_source_record,
)
from env_loader import load_dotenv
from models import (
    CallForPaper,
    ScrapingStatus,
    SearchCreate,
    SearchUpdate,
    Source,
    SourceCreate,
    SourceUpdate,
)
from scraper_factory import create_scraper, is_supported_scraper_type, list_scraper_types
from search_notifications import notify_searches
from source_discovery import discover_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()
init_db()

app = FastAPI(title="Call for Papers Explorer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory cache ──────────────────────────────────────────────────────────

_cache: dict = {
    "data": [],
    "statuses": [],
    "search_notifications": [],
    "timestamp": None,
}
CACHE_TTL = timedelta(hours=1)

# ── Scraping logic ────────────────────────────────────────────────────────────


async def _run_scrapers(
    sources: list[Source] | None = None,
) -> tuple[List[CallForPaper], List[ScrapingStatus]]:
    sources = sources if sources is not None else list_sources(enabled_only=True)
    logger.info("Running enabled sources: %s", [s.name for s in sources])

    jobs = []
    statuses: List[ScrapingStatus] = []

    for source in sources:
        try:
            jobs.append((source, create_scraper(source)))
        except Exception as exc:
            logger.error("[%s] Source setup error: %s", source.name, exc)
            status_obj = ScrapingStatus(
                source_id=source.id,
                source=source.name,
                success=False,
                count=0,
                error=str(exc),
            )
            statuses.append(status_obj)
            record_source_run(
                source.id, success=False, count=0, error=status_obj.error
            )

    if not jobs:
        return [], statuses

    results = await asyncio.gather(
        *[scraper.scrape() for _, scraper in jobs], return_exceptions=True
    )

    all_cfps: List[CallForPaper] = []
    seen: set[str] = set()

    for (source, scraper), result in zip(jobs, results):
        if isinstance(result, Exception):
            logger.error("[%s] Unexpected error: %s", scraper.source_name, result)
            status_obj = ScrapingStatus(
                source_id=source.id,
                source=scraper.source_name,
                success=False,
                count=0,
                error=str(result),
            )
            statuses.append(status_obj)
        else:
            cfps, status_obj = result
            if status_obj.source_id is None:
                status_obj.source_id = source.id
            statuses.append(status_obj)
            for cfp in cfps:
                if cfp.id not in seen:
                    seen.add(cfp.id)
                    all_cfps.append(cfp)

        record_source_run(
            source.id,
            success=status_obj.success,
            count=status_obj.count,
            error=status_obj.error,
        )

    logger.info("Total unique CFPs collected: %d", len(all_cfps))
    return all_cfps, statuses


def _cache_is_valid() -> bool:
    return (
        _cache["timestamp"] is not None
        and datetime.now() - _cache["timestamp"] < CACHE_TTL
    )


def _clear_cache() -> None:
    _cache["data"] = []
    _cache["statuses"] = []
    _cache["search_notifications"] = []
    _cache["timestamp"] = None


def _validate_source_payload(payload: SourceCreate | SourceUpdate) -> None:
    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=400, detail="El nombre de la fuente es obligatorio")
    if payload.url is not None and not payload.url.strip():
        raise HTTPException(status_code=400, detail="La URL de la fuente es obligatoria")
    if payload.scraper_type is not None and not is_supported_scraper_type(payload.scraper_type):
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de scraper no soportado: {payload.scraper_type}",
        )


def _validate_search_payload(payload: SearchCreate | SearchUpdate) -> None:
    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=400, detail="El nombre de la búsqueda es obligatorio")
    if payload.email is not None:
        email = payload.email.strip()
        if not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise HTTPException(status_code=400, detail="El correo electrónico no es válido")
    if payload.keywords_text is not None and not payload.keywords_text.strip():
        raise HTTPException(status_code=400, detail="Las palabras clave son obligatorias")


async def _run_search_notifications(cfps: list[CallForPaper]) -> list[dict]:
    searches = list_searches(enabled_only=True)
    if not searches:
        return []

    results = await notify_searches(searches, cfps)
    response: list[dict] = []

    for result in results:
        record_search_run(
            result.search_id,
            match_count=result.match_count,
            notified=result.notified,
            error=result.error,
        )
        response.append(
            {
                "search_id": result.search_id,
                "search": result.search_name,
                "match_count": result.match_count,
                "notified": result.notified,
                "error": result.error,
            }
        )

    return response


# ── API routes ────────────────────────────────────────────────────────────────


@app.get("/api/cfp")
async def get_cfp(
    source: Optional[str] = Query(None, description="Filtrar por fuente (Taylor & Francis / APA)"),
    q: Optional[str] = Query(None, description="Búsqueda por texto en título, revista o descripción"),
    refresh: bool = Query(False, description="Forzar actualización ignorando caché"),
):
    global _cache

    if not _cache_is_valid() or refresh:
        logger.info("Cache miss or forced refresh — fetching data...")
        try:
            cfps, statuses = await _run_scrapers()
            search_notifications = await _run_search_notifications(cfps)
            _cache["data"] = cfps
            _cache["statuses"] = [s.model_dump() for s in statuses]
            _cache["search_notifications"] = search_notifications
            _cache["timestamp"] = datetime.now()
        except Exception as exc:
            logger.error("Fatal error running scrapers: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": f"Error al obtener datos: {exc}", "data": []},
            )

    results: List[CallForPaper] = list(_cache["data"])

    if source:
        src_lower = source.lower()
        results = [r for r in results if src_lower in r.source.lower()]

    if q:
        q_lower = q.lower()
        results = [
            r
            for r in results
            if q_lower in r.title.lower()
            or (r.journal != "No disponible" and q_lower in r.journal.lower())
            or (r.description != "No disponible" and q_lower in r.description.lower())
        ]

    return {
        "data": results,
        "meta": {
            "total": len(results),
            "cached_at": _cache["timestamp"].isoformat() if _cache["timestamp"] else None,
            "statuses": _cache["statuses"],
            "search_notifications": _cache["search_notifications"],
        },
    }


@app.get("/api/source-types")
async def get_source_types():
    return {"data": list_scraper_types()}


@app.get("/api/sources")
async def get_sources(enabled_only: bool = Query(False)):
    return {"data": list_sources(enabled_only=enabled_only)}


@app.post("/api/sources", status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceCreate):
    _validate_source_payload(payload)
    source_payload = payload
    if not payload.scraper_type:
        scraper_type, settings = await discover_source(payload.name, payload.url)
        source_payload = SourceCreate(
            name=payload.name,
            scraper_type=scraper_type,
            url=payload.url,
            enabled=payload.enabled,
            settings={**settings, **payload.settings},
        )
    _validate_source_payload(source_payload)
    source = create_source_record(source_payload)
    _clear_cache()
    return {"data": source}


@app.get("/api/sources/{source_id}")
async def read_source(source_id: int):
    source = get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return {"data": source}


@app.put("/api/sources/{source_id}")
async def update_source(source_id: int, payload: SourceUpdate):
    _validate_source_payload(payload)
    source = update_source_record(source_id, payload)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    _clear_cache()
    return {"data": source}


@app.patch("/api/sources/{source_id}/enable")
async def enable_source(source_id: int):
    source = set_source_enabled(source_id, True)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    _clear_cache()
    return {"data": source}


@app.patch("/api/sources/{source_id}/disable")
async def disable_source(source_id: int):
    source = set_source_enabled(source_id, False)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    _clear_cache()
    return {"data": source}


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: int):
    deleted = delete_source_record(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    _clear_cache()
    return {"deleted": True}


@app.get("/api/searches")
async def get_searches(enabled_only: bool = Query(False)):
    return {"data": list_searches(enabled_only=enabled_only)}


@app.post("/api/searches", status_code=status.HTTP_201_CREATED)
async def create_search(payload: SearchCreate):
    _validate_search_payload(payload)
    search = create_search_record(payload)
    return {"data": search}


@app.get("/api/searches/{search_id}")
async def read_search(search_id: int):
    search = get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return {"data": search}


@app.put("/api/searches/{search_id}")
async def update_search(search_id: int, payload: SearchUpdate):
    _validate_search_payload(payload)
    search = update_search_record(search_id, payload)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return {"data": search}


@app.patch("/api/searches/{search_id}/enable")
async def enable_search(search_id: int):
    search = set_search_enabled(search_id, True)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return {"data": search}


@app.patch("/api/searches/{search_id}/disable")
async def disable_search(search_id: int):
    search = set_search_enabled(search_id, False)
    if search is None:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return {"data": search}


@app.delete("/api/searches/{search_id}")
async def delete_search(search_id: int):
    deleted = delete_search_record(search_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Búsqueda no encontrada")
    return {"deleted": True}


@app.post("/api/sources/{source_id}/test")
async def test_source(source_id: int):
    source = get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")

    cfps, statuses = await _run_scrapers([source])
    return {
        "data": cfps[:5],
        "meta": {
            "total": len(cfps),
            "statuses": [s.model_dump() for s in statuses],
        },
    }


@app.post("/api/sources/{source_id}/refresh")
async def refresh_source(source_id: int):
    source = get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")

    cfps, statuses = await _run_scrapers([source])
    search_notifications = await _run_search_notifications(cfps)
    _clear_cache()
    return {
        "data": cfps,
        "meta": {
            "total": len(cfps),
            "statuses": [s.model_dump() for s in statuses],
            "search_notifications": search_notifications,
        },
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "cache_valid": _cache_is_valid(),
        "cached_items": len(_cache["data"]),
    }


# ── Serve frontend ────────────────────────────────────────────────────────────

_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
    logger.info("Serving frontend from %s", _frontend)
else:
    logger.warning("Frontend directory not found at %s", _frontend)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
