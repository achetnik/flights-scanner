import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.ryanair import RyanairScraper

MOCK_API_RESPONSE = {
    "trips": [
        {
            "origin": "TLV",
            "destination": "FCO",
            "dates": [
                {
                    "dateOut": "2025-06-14T00:00:00.000",
                    "flights": [
                        {
                            "flightNumber": "FR1234",
                            "regularFare": {
                                "fares": [{"amount": 89.99}]
                            },
                            "time": ["2025-06-14T06:00:00.000", "2025-06-14T09:00:00.000"],
                        }
                    ],
                }
            ],
        }
    ]
}


@pytest.mark.asyncio
async def test_ryanair_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_API_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "ryanair"
    assert flights[0].flight_number == "FR1234"
    assert flights[0].price_eur == 89.99
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "ryanair.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_ryanair_returns_empty_on_no_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    empty_response = {"trips": [{"origin": "TLV", "destination": "FCO", "dates": []}]}

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert flights == []


@pytest.mark.asyncio
async def test_ryanair_extracts_times():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_API_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert flights[0].departure_time == time(6, 0)
    assert flights[0].arrival_time == time(9, 0)


@pytest.mark.asyncio
async def test_ryanair_get_destinations():
    mock_routes = [
        {"arrivalAirport": {"code": "BCN", "name": "Barcelona"}},
        {"arrivalAirport": {"code": "AGP", "name": "Malaga"}},
    ]

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = mock_routes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        dests = await scraper.get_destinations("BRS")

    assert dests == ["BCN", "AGP"]
