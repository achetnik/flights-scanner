import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.wizzair import WizzairScraper

# Mock timetable response — the only endpoint we use.
# Each outboundFlight has a price + list of departure date-times.
MOCK_WIZZAIR_TIMETABLE_RESPONSE = {
    "outboundFlights": [
        {
            "departureStation": "LTN",
            "arrivalStation": "SOF",
            "price": {"amount": 65.0, "currencyCode": "GBP"},
            "departureDates": [
                "2025-06-14T08:20:00",
                "2025-06-14T15:40:00",
            ],
        }
    ],
    "returnFlights": None,
}

# Multi-day: different prices on different days.
MOCK_WIZZAIR_TIMETABLE_MULTIDAY = {
    "outboundFlights": [
        {
            "departureStation": "LTN",
            "arrivalStation": "BUD",
            "price": {"amount": 50.0, "currencyCode": "GBP"},
            "departureDates": ["2025-06-14T08:30:00", "2025-06-14T19:20:00"],
        },
        {
            "departureStation": "LTN",
            "arrivalStation": "BUD",
            "price": {"amount": 72.0, "currencyCode": "GBP"},
            "departureDates": ["2025-06-15T08:30:00"],
        },
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
    if method != "get":
        version_response = MagicMock()
        version_response.text = "SSR https://be.wizzair.com/28.1.0"
        version_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=version_response)
    return mock_client


# ---- Timetable parsing tests ----

@pytest.mark.asyncio
async def test_wizzair_parses_timetable_response():
    """Timetable returns prices and departure times; arrival is estimated."""
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = _make_mock_client(MOCK_WIZZAIR_TIMETABLE_RESPONSE)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert len(flights) == 2
    assert flights[0].airline == "wizzair"
    assert flights[0].price_gbp == 65.0
    assert flights[0].departure_date == date(2025, 6, 14)
    assert flights[0].departure_time == time(8, 20)
    # Estimated arrival: 08:20 + 3h = 11:20
    assert flights[0].arrival_time == time(11, 20)
    assert flights[1].departure_time == time(15, 40)
    # Estimated arrival: 15:40 + 3h = 18:40
    assert flights[1].arrival_time == time(18, 40)
    assert "wizzair.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_wizzair_multiday_timetable():
    """A multi-day search returns flights across days in one API call."""
    job = JobConfig(
        origin="LTN",
        destinations=["BUD"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 15),
    )

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = _make_mock_client(MOCK_WIZZAIR_TIMETABLE_MULTIDAY)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "BUD", job)

    # 2 flights on day 1 + 1 flight on day 2 = 3 total
    assert len(flights) == 3
    assert flights[0].price_gbp == 50.0
    assert flights[0].departure_date == date(2025, 6, 14)
    assert flights[2].price_gbp == 72.0
    assert flights[2].departure_date == date(2025, 6, 15)


@pytest.mark.asyncio
async def test_wizzair_skips_zero_price_flights():
    """Flights with zero price are excluded."""
    response = {
        "outboundFlights": [
            {
                "departureStation": "LTN",
                "arrivalStation": "SOF",
                "price": {"amount": 0, "currencyCode": "GBP"},
                "departureDates": ["2025-06-14T10:00:00"],
            },
        ],
        "returnFlights": None,
    }
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = _make_mock_client(response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert flights == []


# ---- Empty / error handling ----

@pytest.mark.asyncio
async def test_wizzair_empty_on_no_flights():
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
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


# ---- Version & destination tests ----

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
