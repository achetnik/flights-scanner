# tests/test_base_scraper.py
import pytest
from datetime import date
from models import JobConfig, FlightResult
from scrapers.base import BaseScraper


class ConcreteTestScraper(BaseScraper):
    airline_name = "test"

    async def search(self, origin: str, destination: str, job: JobConfig) -> list[FlightResult]:
        return [
            FlightResult(
                airline="test",
                origin=origin,
                destination=destination,
                departure_date=date(2025, 6, 14),
                price_gbp=99.0,
                booking_url="https://test.com",
                flight_number="T001",
            )
        ]


@pytest.mark.asyncio
async def test_scraper_returns_flights():
    scraper = ConcreteTestScraper()
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["test"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 8, 31),
    )
    flights = await scraper.search("TLV", "FCO", job)
    assert len(flights) == 1
    assert flights[0].airline == "test"
    assert flights[0].origin == "TLV"
    assert flights[0].destination == "FCO"


def test_base_scraper_cannot_be_instantiated_without_airline_name():
    class BadScraper(BaseScraper):
        async def search(self, origin, destination, job):
            return []

    # Missing airline_name — should raise
    with pytest.raises(TypeError):
        BadScraper()
