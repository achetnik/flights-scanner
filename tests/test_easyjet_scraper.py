# tests/test_easyjet_scraper.py
import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.easyjet import EasyJetScraper

MOCK_EJ_RESPONSE = {
    "Flights": [
        {
            "FlightNumber": "EJU1234",
            "DepartureDateTime": "2025-06-14T07:30:00",
            "ArrivalDateTime": "2025-06-14T10:30:00",
            "Prices": [
                {"FareType": "Standard", "Amount": 105.00},
            ],
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

    with patch.object(EasyJetScraper, "_get_session_cookies", new_callable=AsyncMock) as mock_cookies, \
         patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:

        mock_cookies.return_value = {"_abck": "fake"}
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
    assert flights[0].price_gbp == 105.00
    assert flights[0].departure_date == date(2025, 6, 14)
    assert flights[0].departure_time == time(7, 30)
    assert flights[0].arrival_time == time(10, 30)
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
    empty_response = {"Flights": []}

    with patch.object(EasyJetScraper, "_get_session_cookies", new_callable=AsyncMock) as mock_cookies, \
         patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:

        mock_cookies.return_value = {}
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


@pytest.mark.asyncio
async def test_easyjet_handles_timeout_gracefully():
    import httpx as httpx_mod

    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["easyjet"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch.object(EasyJetScraper, "_get_session_cookies", new_callable=AsyncMock) as mock_cookies, \
         patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:

        mock_cookies.return_value = {}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx_mod.ReadTimeout("timeout"))
        mock_client_cls.return_value = mock_client

        scraper = EasyJetScraper()
        flights = await scraper.search("TLV", "FCO", job)

    # Should return empty, not raise
    assert flights == []
