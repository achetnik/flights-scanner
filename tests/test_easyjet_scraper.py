# tests/test_easyjet_scraper.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.easyjet import EasyJetScraper

MOCK_EJ_RESPONSE = {
    "outboundFlights": [
        {
            "id": "EJU1234",
            "departureDateTime": "2025-06-14T07:30:00",
            "arrivalDateTime": "2025-06-14T10:30:00",
            "priceInPennies": 8999,
            "currency": "GBP",
            "priceInEur": 10500,
        }
    ]
}


@pytest.mark.asyncio
async def test_easyjet_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["easyjet"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_EJ_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = EasyJetScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "easyjet"
    assert flights[0].flight_number == "EJU1234"
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "easyjet.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_easyjet_empty_on_no_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["easyjet"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )
    empty_response = {"outboundFlights": []}

    with patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = EasyJetScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert flights == []
