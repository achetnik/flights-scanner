import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.wizzair import WizzairScraper

# Mock response matching the /Api/search/search endpoint format
MOCK_WIZZAIR_SEARCH_RESPONSE = {
    "outboundFlights": [
        {
            "departureStation": "LTN",
            "arrivalStation": "SOF",
            "departureDateTime": "2025-06-14T08:20:00",
            "arrivalDateTime": "2025-06-14T13:15:00",
            "flightNumber": "W61234",
            "fares": [
                {
                    "bundle": "BASIC",
                    "basePrice": {"amount": 75.0, "currencyCode": "GBP"},
                    "discountedPrice": {"amount": 65.0, "currencyCode": "GBP"},
                },
                {
                    "bundle": "MIDDLE",
                    "basePrice": {"amount": 120.0, "currencyCode": "GBP"},
                    "discountedPrice": {"amount": 0, "currencyCode": "GBP"},
                },
            ],
        },
        {
            "departureStation": "LTN",
            "arrivalStation": "SOF",
            "departureDateTime": "2025-06-14T15:40:00",
            "arrivalDateTime": "2025-06-14T20:30:00",
            "flightNumber": "W65678",
            "fares": [
                {
                    "bundle": "BASIC",
                    "basePrice": {"amount": 80.0, "currencyCode": "GBP"},
                    "discountedPrice": {"amount": 70.0, "currencyCode": "GBP"},
                },
            ],
        },
    ],
    "returnFlights": [],
}

# Mock response matching the /Api/search/timetable endpoint format
MOCK_WIZZAIR_TIMETABLE_RESPONSE = {
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


# ---- Search endpoint tests (preferred path) ----

@pytest.mark.asyncio
async def test_wizzair_parses_search_response():
    """When the search endpoint returns results, use real arrival times."""
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
        mock_client = _make_mock_client(MOCK_WIZZAIR_SEARCH_RESPONSE)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert len(flights) == 2
    assert flights[0].airline == "wizzair"
    assert flights[0].price_gbp == 65.0  # discounted price (cheapest fare)
    assert flights[0].departure_date == date(2025, 6, 14)
    assert flights[0].departure_time == time(8, 20)
    assert flights[0].arrival_time == time(13, 15)  # real arrival time
    assert flights[0].flight_number == "W61234"
    assert flights[1].departure_time == time(15, 40)
    assert flights[1].arrival_time == time(20, 30)
    assert flights[1].price_gbp == 70.0
    assert "wizzair.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_wizzair_uses_base_price_when_no_discount():
    """When discountedPrice is 0, fall back to basePrice."""
    response = {
        "outboundFlights": [
            {
                "departureStation": "LTN",
                "arrivalStation": "SOF",
                "departureDateTime": "2025-06-14T10:00:00",
                "arrivalDateTime": "2025-06-14T15:00:00",
                "flightNumber": "W69999",
                "fares": [
                    {
                        "bundle": "BASIC",
                        "basePrice": {"amount": 90.0, "currencyCode": "GBP"},
                        "discountedPrice": {"amount": 0, "currencyCode": "GBP"},
                    },
                ],
            },
        ],
        "returnFlights": [],
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

    assert len(flights) == 1
    assert flights[0].price_gbp == 90.0  # base price used


# ---- Timetable fallback tests ----

@pytest.mark.asyncio
async def test_wizzair_falls_back_to_timetable():
    """When the search endpoint returns empty, fall back to timetable
    and produce estimated arrival times."""
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )
    empty_search = {"outboundFlights": [], "returnFlights": []}

    call_count = 0

    async def _mock_post(url, json=None, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "search/search" in url:
            resp.json.return_value = empty_search
        elif "search/timetable" in url:
            resp.json.return_value = MOCK_WIZZAIR_TIMETABLE_RESPONSE
        return resp

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_mock_post)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    assert len(flights) == 2
    assert flights[0].price_gbp == 75.0
    assert flights[0].departure_time == time(8, 20)
    # Estimated arrival: 08:20 + 3h = 11:20
    assert flights[0].arrival_time == time(11, 20)
    assert flights[1].departure_time == time(15, 40)
    # Estimated arrival: 15:40 + 3h = 18:40
    assert flights[1].arrival_time == time(18, 40)


@pytest.mark.asyncio
async def test_wizzair_skips_search_after_first_failure():
    """After the search endpoint fails once, subsequent days go
    directly to the timetable without trying search again."""
    job = JobConfig(
        origin="LTN",
        destinations=["SOF"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 15),  # 2 days
    )
    empty_search = {"outboundFlights": [], "returnFlights": []}
    search_calls = 0
    timetable_calls = 0

    async def _mock_post(url, json=None, **kwargs):
        nonlocal search_calls, timetable_calls
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "search/search" in url:
            search_calls += 1
            resp.json.return_value = empty_search
        elif "search/timetable" in url:
            timetable_calls += 1
            resp.json.return_value = MOCK_WIZZAIR_TIMETABLE_RESPONSE
        return resp

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_mock_post)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("LTN", "SOF", job)

    # Search tried once (day 1), then skipped for day 2
    assert search_calls == 1
    # Timetable used for both days
    assert timetable_calls == 2
    # Got flights from both days
    assert len(flights) == 4


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
    empty_response = {"outboundFlights": [], "returnFlights": []}

    async def _mock_post(url, json=None, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = empty_response
        return resp

    with patch.object(WizzairScraper, "_get_api_version", new_callable=AsyncMock) as mock_ver, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_ver.return_value = "28.1.0"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_mock_post)
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
