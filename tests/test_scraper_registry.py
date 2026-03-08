import pytest
from scrapers.registry import get_scraper, list_scrapers
from scrapers.ryanair import RyanairScraper
from scrapers.easyjet import EasyJetScraper
from scrapers.wizzair import WizzairScraper
from scrapers.googleflights import GoogleFlightsScraper


def test_get_scraper_ryanair():
    scraper = get_scraper("ryanair")
    assert isinstance(scraper, RyanairScraper)


def test_get_scraper_easyjet():
    scraper = get_scraper("easyjet")
    assert isinstance(scraper, EasyJetScraper)


def test_get_scraper_wizzair():
    scraper = get_scraper("wizzair")
    assert isinstance(scraper, WizzairScraper)


def test_get_scraper_googleflights():
    scraper = get_scraper("googleflights")
    assert isinstance(scraper, GoogleFlightsScraper)


def test_get_scraper_unknown_raises():
    with pytest.raises(ValueError, match="Unknown airline"):
        get_scraper("unknownair")


def test_list_scrapers():
    names = list_scrapers()
    assert "ryanair" in names
    assert "easyjet" in names
    assert "wizzair" in names
    assert "googleflights" in names
