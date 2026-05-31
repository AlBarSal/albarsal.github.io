from .taylor_francis import TaylorFrancisScraper
from .apa import APAScraper
from .generic_html import GenericHtmlScraper
from .sciencedirect import ScienceDirectScraper
from .sage import SageScraper

__all__ = [
    "TaylorFrancisScraper",
    "APAScraper",
    "GenericHtmlScraper",
    "ScienceDirectScraper",
    "SageScraper",
]
