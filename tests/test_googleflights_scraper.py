import pytest
from datetime import date, time
from unittest.mock import MagicMock, patch
from models import JobConfig
from scrapers.googleflights import GoogleFlightsScraper


# ---------------------------------------------------------------------------
# Mock helpers — simulate fast-flights Result / Flight objects
# ---------------------------------------------------------------------------

def _make_mock_flight(
    name="Ryanair",
    departure="10:00 AM",
    arrival="1:30 PM",
    price="£65",
    stops=0,
    is_best=True,
    duration="3h 30m",
    delay=None,
    arrival_time_ahead=None,
):
    flight = MagicMock()
    flight.name = name
    flight.departure = departure
    flight.arrival = arrival
    flight.price = price
    flight.stops = stops
    flight.is_best = is_best
    flight.duration = duration
    flight.delay = delay
    flight.arrival_time_ahead = arrival_time_ahead
    return flight


def _make_mock_result(flights=None, current_price="typical"):
    result = MagicMock()
    result.flights = flights or []
    result.current_price = current_price
    return result


# ---------------------------------------------------------------------------
# Integration-style tests (mock at _call_fast_flights boundary)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_googleflights_parses_flights():
    """Standard single-flight result is parsed into a FlightResult."""
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 15),
    )
    mock_result = _make_mock_result(flights=[
        _make_mock_flight(
            name="Ryanair",
            departure="10:00 AM",
            arrival="1:30 PM",
            price="£65",
        ),
    ])

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights", return_value=mock_result,
    ):
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert len(flights) == 1
    f = flights[0]
    assert f.airline == "ryanair"
    assert f.price_gbp == 65.0
    assert f.departure_date == date(2026, 6, 15)
    assert f.departure_time == time(10, 0)
    assert f.arrival_time == time(13, 30)
    assert "google.com/travel/flights" in f.booking_url
    assert f.flight_number.startswith("GF-")


@pytest.mark.asyncio
async def test_googleflights_multiple_airlines():
    """Results from different airlines are all returned."""
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 15),
    )
    mock_result = _make_mock_result(flights=[
        _make_mock_flight(name="Ryanair", price="£45", departure="6:30 AM", arrival="10:00 AM"),
        _make_mock_flight(name="EasyJet", price="£72", departure="2:00 PM", arrival="5:30 PM"),
        _make_mock_flight(name="British Airways", price="£120", departure="8:00 AM", arrival="11:15 AM"),
    ])

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights", return_value=mock_result,
    ):
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert len(flights) == 3
    assert flights[0].airline == "ryanair"
    assert flights[1].airline == "easyjet"
    assert flights[2].airline == "british airways"


@pytest.mark.asyncio
async def test_googleflights_returns_empty_on_no_flights():
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 15),
    )
    mock_result = _make_mock_result(flights=[])

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights", return_value=mock_result,
    ):
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert flights == []


@pytest.mark.asyncio
async def test_googleflights_skips_no_price_flights():
    """Flights without a price are excluded."""
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 15),
    )
    mock_result = _make_mock_result(flights=[
        _make_mock_flight(name="Ryanair", price=None),
        _make_mock_flight(name="EasyJet", price="£89"),
    ])

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights", return_value=mock_result,
    ):
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert len(flights) == 1
    assert flights[0].airline == "easyjet"
    assert flights[0].price_gbp == 89.0


@pytest.mark.asyncio
async def test_googleflights_handles_exception_gracefully():
    """An exception from fast-flights returns [] instead of crashing."""
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 15),
    )

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights",
        side_effect=Exception("Google blocked us"),
    ):
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert flights == []


@pytest.mark.asyncio
async def test_googleflights_iterates_date_range():
    """A 3-day range calls _call_fast_flights once per day."""
    job = JobConfig(
        origin="BRS",
        destinations=["BCN"],
        airlines=["googleflights"],
        date_from=date(2026, 6, 15),
        date_to=date(2026, 6, 17),
    )
    mock_result = _make_mock_result(flights=[
        _make_mock_flight(name="Vueling", price="£55"),
    ])

    with patch.object(
        GoogleFlightsScraper, "_call_fast_flights", return_value=mock_result,
    ) as mock_call:
        scraper = GoogleFlightsScraper()
        flights = await scraper.search("BRS", "BCN", job)

    assert mock_call.call_count == 3
    assert len(flights) == 3
    # Each day should get the correct departure_date
    assert flights[0].departure_date == date(2026, 6, 15)
    assert flights[1].departure_date == date(2026, 6, 16)
    assert flights[2].departure_date == date(2026, 6, 17)


@pytest.mark.asyncio
async def test_googleflights_get_destinations_returns_empty():
    """Google Flights has no route discovery — must return []."""
    scraper = GoogleFlightsScraper()
    dests = await scraper.get_destinations("BRS")
    assert dests == []


# ---------------------------------------------------------------------------
# Unit tests — _parse_price
# ---------------------------------------------------------------------------

def test_parse_price_gbp():
    assert GoogleFlightsScraper._parse_price("£65") == 65.0


def test_parse_price_usd():
    assert GoogleFlightsScraper._parse_price("$120.50") == 120.50


def test_parse_price_euro():
    assert GoogleFlightsScraper._parse_price("€89") == 89.0


def test_parse_price_with_comma():
    assert GoogleFlightsScraper._parse_price("£1,250") == 1250.0


def test_parse_price_none():
    assert GoogleFlightsScraper._parse_price(None) is None


def test_parse_price_numeric():
    assert GoogleFlightsScraper._parse_price(75.0) == 75.0


def test_parse_price_int():
    assert GoogleFlightsScraper._parse_price(42) == 42.0


def test_parse_price_empty_string():
    assert GoogleFlightsScraper._parse_price("") is None


def test_parse_price_no_digits():
    assert GoogleFlightsScraper._parse_price("free") is None


# ---------------------------------------------------------------------------
# Unit tests — _parse_time
# ---------------------------------------------------------------------------

def test_parse_time_12h_am():
    assert GoogleFlightsScraper._parse_time("10:00 AM") == time(10, 0)


def test_parse_time_12h_pm():
    assert GoogleFlightsScraper._parse_time("2:30 PM") == time(14, 30)


def test_parse_time_12h_no_space():
    assert GoogleFlightsScraper._parse_time("2:30PM") == time(14, 30)


def test_parse_time_24h():
    assert GoogleFlightsScraper._parse_time("14:30") == time(14, 30)


def test_parse_time_24h_with_seconds():
    assert GoogleFlightsScraper._parse_time("14:30:00") == time(14, 30)


def test_parse_time_midnight_12h():
    assert GoogleFlightsScraper._parse_time("12:00 AM") == time(0, 0)


def test_parse_time_noon_12h():
    assert GoogleFlightsScraper._parse_time("12:00 PM") == time(12, 0)


def test_parse_time_none():
    assert GoogleFlightsScraper._parse_time(None) is None


def test_parse_time_invalid():
    assert GoogleFlightsScraper._parse_time("not a time") is None


def test_parse_time_extended_pm():
    """Library returns '5:35 PM on Mon, Jun 15' — strip suffix."""
    assert GoogleFlightsScraper._parse_time("5:35 PM on Mon, Jun 15") == time(17, 35)


def test_parse_time_extended_am():
    assert GoogleFlightsScraper._parse_time("10:40 AM on Mon, Jun 15") == time(10, 40)


def test_parse_time_extended_arrival():
    assert GoogleFlightsScraper._parse_time("8:45 PM on Mon, Jun 15") == time(20, 45)


# ---------------------------------------------------------------------------
# Unit tests — _synthesize_flight_number
# ---------------------------------------------------------------------------

def test_synthesize_flight_number():
    fn = GoogleFlightsScraper._synthesize_flight_number(
        "Ryanair", "BRS", "BCN", date(2026, 6, 15), time(10, 0),
    )
    assert fn == "GF-R-BRSBCN-1000"


def test_synthesize_flight_number_multi_word():
    fn = GoogleFlightsScraper._synthesize_flight_number(
        "British Airways", "LHR", "JFK", date(2026, 6, 15), time(8, 30),
    )
    assert fn == "GF-BA-LHRJFK-0830"


def test_synthesize_flight_number_no_time():
    fn = GoogleFlightsScraper._synthesize_flight_number(
        "EasyJet", "BRS", "BCN", date(2026, 6, 15), None,
    )
    assert fn == "GF-E-BRSBCN-0000"
