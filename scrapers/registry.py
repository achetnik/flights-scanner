from typing import List
from scrapers.base import BaseScraper
from scrapers.ryanair import RyanairScraper
from scrapers.easyjet import EasyJetScraper
from scrapers.wizzair import WizzairScraper
from scrapers.googleflights import GoogleFlightsScraper

_REGISTRY = {
    "ryanair": RyanairScraper,
    "easyjet": EasyJetScraper,
    "wizzair": WizzairScraper,
    "googleflights": GoogleFlightsScraper,
}


def get_scraper(airline: str) -> BaseScraper:
    cls = _REGISTRY.get(airline.lower())
    if not cls:
        raise ValueError(f"Unknown airline: {airline}. Available: {list(_REGISTRY.keys())}")
    return cls()


def list_scrapers() -> List[str]:
    return list(_REGISTRY.keys())
