from typing import Any

from models import Source
from scrapers import APAScraper, GenericHtmlScraper, ScienceDirectScraper, TaylorFrancisScraper
from scrapers.base import BaseScraper


SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "taylor_francis": TaylorFrancisScraper,
    "apa": APAScraper,
    "sciencedirect": ScienceDirectScraper,
    "generic_html": GenericHtmlScraper,
}


SCRAPER_TYPES: list[dict[str, Any]] = [
    {
        "type": "taylor_francis",
        "label": "Taylor & Francis",
        "settings": {
            "api_url": "WordPress REST API endpoint",
            "page_size": "Items por página",
            "max_pages": "Máximo de páginas API",
            "max_detail_fetch": "Páginas de detalle a enriquecer",
            "concurrency": "Peticiones paralelas",
        },
    },
    {
        "type": "apa",
        "label": "APA",
        "settings": {},
    },
    {
        "type": "sciencedirect",
        "label": "ScienceDirect (vía Scopus API)",
        "settings": {
            "count": "Número máximo de CFPs a recuperar (por defecto 200)",
            "months": "Meses hacia atrás a buscar (por defecto 12)",
        },
    },
    {
        "type": "generic_html",
        "label": "HTML genérico",
        "settings": {
            "item_selector": "CSS selector para cada convocatoria",
            "title_selector": "CSS selector del título dentro del item",
            "url_selector": "CSS selector del enlace dentro del item",
            "journal_selector": "CSS selector de revista",
            "deadline_selector": "CSS selector de fecha límite",
            "description_selector": "CSS selector de descripción",
        },
    },
]


def create_scraper(source: Source) -> BaseScraper:
    scraper_cls = SCRAPER_REGISTRY.get(source.scraper_type)
    if scraper_cls is None:
        raise ValueError(f"Tipo de scraper no soportado: {source.scraper_type}")
    return scraper_cls(source=source)


def is_supported_scraper_type(scraper_type: str) -> bool:
    return scraper_type in SCRAPER_REGISTRY


def list_scraper_types() -> list[dict[str, Any]]:
    return SCRAPER_TYPES
