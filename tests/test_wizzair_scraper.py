import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.wizzair import WizzairScraper

MOCK_WIZZAIR_RESPONSE = {
    "outboundFlights": [
        {
            "departureStation": "LTN",
            "arrivalStation": "SOF",
            "departureDate": "2025-06-14T00:00:00",
            "price": {"amount": 75.0, "currencyCode": "GBP"},
            "departureDates": ["2025-06-14T08:20:00", "2025-06-14T15:40:00"],
            "hasMacFlight": False,
        }
    ],
    "returnFlights": None,
}


def _make_mock_client(response_data, method="post"):
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    setattr(mock_client, method, AsyncMock(return_value=mock_response))
    # Also set get for version lookup
    if method != "get":
        version_response = MagicMock()
        version_response.text = "SSR https://be.wizzair.com/28.1.0"
        version_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=version_response)
    return mock_client


@pytest.mark.asyncio
async def test_wizzair_parses_flights():
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 6, 30),
    )

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = _make_mock_client(MOCK_WIZZAIR_RESPONSE)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert len(flights) == 2  # Two departure times for the same date
    assert flights[0].airline == "wizzair"
    assert flights[0].price_eur == 75.0
    assert flights[0].departure_date == date(2025, 6, 14)
    assert flights[0].departure_time == time(8, 20)
    assert flights[1].departure_time == time(15, 40)
    assert "wizzair.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_wizzair_empty_on_no_flights():
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 6, 30),
    )
    empty_response = {"outboundFlights": [], "returnFlights": None}

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = _make_mock_client(empty_response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert flights == []


@pytest.mark.asyncio
async def test_wizzair_get_api_version():
    with patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.text = "SSR https://be.wizzair.com/28.1.0"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        version = await scraper._get_api_version()

    assert version == "28.1.0"


@pytest.mark.asyncio
async def test_wizzair_get_destinations():
    mock_map = {
        "cities": [
            {
                "iata": "LTN",
                "connections": [
                    {"iata": "SOF"},
                    {"iata": "BUD"},
                ],
            },
            {
                "iata": "BRS",
                "connections": [{"iata": "BCN"}],
            },
        ]
    }

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_response = MagicMock()
        mock_response.json.return_value = mock_map
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        dests = await scraper.get_destinations("LTN")

    assert dests == ["SOF", "BUD"]
