import pytest
from datetime import date, time
from unittest.mock import AsyncMock, patch

from models import FlightResult
from daytrips import (
    DayTripResult,
    _qualifies_outbound,
    _qualifies_return,
    search_day_trips,
    format_day_trip,
)


def _flight(
    airline="ryanair",
    origin="BRS",
    destination="BCN",
    dep_date=date(2025, 6, 14),
    dep_time=None,
    arr_time=None,
    price=50.0,
    flight_number="FR1234",
):
    return FlightResult(
        airline=airline,
        origin=origin,
        destination=destination,
        departure_date=dep_date,
        departure_time=dep_time,
        arrival_time=arr_time,
        price_gbp=price,
        booking_url="https://example.com",
        flight_number=flight_number,
    )


class TestQualifiers:
    def test_outbound_before_midday(self):
        f = _flight(arr_time=time(11, 30))
        assert _qualifies_outbound(f) is True

    def test_outbound_at_midday_fails(self):
        f = _flight(arr_time=time(12, 0))
        assert _qualifies_outbound(f) is False

    def test_outbound_after_midday_fails(self):
        f = _flight(arr_time=time(14, 0))
        assert _qualifies_outbound(f) is False

    def test_outbound_no_time_fails(self):
        f = _flight(arr_time=None)
        assert _qualifies_outbound(f) is False

    def test_return_after_1600(self):
        f = _flight(dep_time=time(16, 30))
        assert _qualifies_return(f) is True

    def test_return_at_1600(self):
        f = _flight(dep_time=time(16, 0))
        assert _qualifies_return(f) is True

    def test_return_before_1600_fails(self):
        f = _flight(dep_time=time(15, 59))
        assert _qualifies_return(f) is False

    def test_return_no_time_fails(self):
        f = _flight(dep_time=None)
        assert _qualifies_return(f) is False


class TestDayTripResult:
    def test_total_price(self):
        out = _flight(price=30.0)
        ret = _flight(price=25.0)
        trip = DayTripResult(outbound=out, return_flight=ret)
        assert trip.total_price == 55.0


class TestSearchDayTrips:
    @pytest.mark.asyncio
    async def test_finds_matching_day_trip(self):
        # Outbound: arrives at 10:00 (before midday) — qualifies
        outbound = _flight(
            origin="BRS", destination="BCN",
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=40.0, flight_number="FR100",
        )
        # Return: departs at 18:00 (after 16:00) — qualifies
        return_fl = _flight(
            airline="wizzair",
            origin="BCN", destination="BRS",
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=35.0, flight_number="W6200",
        )

        async def mock_search(self, origin, destination, job):
            if origin == "BRS" and destination == "BCN":
                return [outbound]
            if origin == "BCN" and destination == "BRS":
                return [return_fl]
            return []

        async def mock_get_dests(self, origin):
            if origin == "BRS":
                return ["BCN"]
            return []

        with patch("daytrips.get_scraper") as mock_get_scraper, \
             patch("daytrips.list_scrapers", return_value=["ryanair"]):

            mock_scraper = AsyncMock()
            mock_scraper.airline_name = "ryanair"
            mock_scraper.search = lambda o, d, j: mock_search(None, o, d, j)
            mock_scraper.get_destinations = lambda o: mock_get_dests(None, o)
            mock_get_scraper.return_value = mock_scraper

            results = await search_day_trips(
                origin="BRS",
                date_from=date(2025, 6, 14),
                date_to=date(2025, 6, 14),
                airlines=["ryanair"],
            )

        assert len(results) == 1
        assert results[0].total_price == 75.0
        assert results[0].outbound.destination == "BCN"
        assert results[0].return_flight.origin == "BCN"

    @pytest.mark.asyncio
    async def test_no_results_when_no_qualifying_flights(self):
        # Outbound arrives at 14:00 (after midday) — does NOT qualify
        outbound = _flight(
            origin="BRS", destination="BCN",
            dep_time=time(11, 0), arr_time=time(14, 0),
            price=40.0,
        )
        # Return departs at 14:00 (before 16:00) — does NOT qualify
        return_fl = _flight(
            origin="BCN", destination="BRS",
            dep_time=time(14, 0), arr_time=time(17, 0),
            price=35.0,
        )

        async def mock_search(self, origin, destination, job):
            if origin == "BRS":
                return [outbound]
            if origin == "BCN":
                return [return_fl]
            return []

        async def mock_get_dests(self, origin):
            return ["BCN"] if origin == "BRS" else []

        with patch("daytrips.get_scraper") as mock_get_scraper, \
             patch("daytrips.list_scrapers", return_value=["ryanair"]):

            mock_scraper = AsyncMock()
            mock_scraper.airline_name = "ryanair"
            mock_scraper.search = lambda o, d, j: mock_search(None, o, d, j)
            mock_scraper.get_destinations = lambda o: mock_get_dests(None, o)
            mock_get_scraper.return_value = mock_scraper

            results = await search_day_trips(
                origin="BRS",
                date_from=date(2025, 6, 14),
                date_to=date(2025, 6, 14),
                airlines=["ryanair"],
            )

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_results_sorted_by_price(self):
        # Two valid outbound flights with different prices
        out_cheap = _flight(
            origin="BRS", destination="BCN",
            dep_time=time(6, 0), arr_time=time(9, 0),
            price=20.0, flight_number="FR100",
        )
        out_expensive = _flight(
            origin="BRS", destination="AGP",
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=80.0, flight_number="FR200",
        )
        ret_bcn = _flight(
            origin="BCN", destination="BRS",
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=25.0, flight_number="FR101",
        )
        ret_agp = _flight(
            origin="AGP", destination="BRS",
            dep_time=time(17, 0), arr_time=time(20, 0),
            price=15.0, flight_number="FR201",
        )

        async def mock_search(self, origin, destination, job):
            if origin == "BRS" and destination == "BCN":
                return [out_cheap]
            if origin == "BRS" and destination == "AGP":
                return [out_expensive]
            if origin == "BCN" and destination == "BRS":
                return [ret_bcn]
            if origin == "AGP" and destination == "BRS":
                return [ret_agp]
            return []

        async def mock_get_dests(self, origin):
            return ["BCN", "AGP"] if origin == "BRS" else []

        with patch("daytrips.get_scraper") as mock_get_scraper, \
             patch("daytrips.list_scrapers", return_value=["ryanair"]):

            mock_scraper = AsyncMock()
            mock_scraper.airline_name = "ryanair"
            mock_scraper.search = lambda o, d, j: mock_search(None, o, d, j)
            mock_scraper.get_destinations = lambda o: mock_get_dests(None, o)
            mock_get_scraper.return_value = mock_scraper

            results = await search_day_trips(
                origin="BRS",
                date_from=date(2025, 6, 14),
                date_to=date(2025, 6, 14),
                airlines=["ryanair"],
            )

        assert len(results) == 2
        # BRS->BCN (20+25=45) should come before BRS->AGP (80+15=95)
        assert results[0].total_price == 45.0
        assert results[1].total_price == 95.0

    @pytest.mark.asyncio
    async def test_empty_when_no_destinations(self):
        with patch("daytrips.get_scraper") as mock_get_scraper, \
             patch("daytrips.list_scrapers", return_value=["ryanair"]):

            mock_scraper = AsyncMock()
            mock_scraper.airline_name = "ryanair"
            mock_scraper.get_destinations = AsyncMock(return_value=[])
            mock_get_scraper.return_value = mock_scraper

            results = await search_day_trips(
                origin="XYZ",
                date_from=date(2025, 6, 14),
                date_to=date(2025, 6, 14),
                airlines=["ryanair"],
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_aggregator_scraper_searches_all_discovered_dests(self):
        """Google Flights (no route discovery) should search destinations
        discovered by other scrapers like Ryanair."""
        outbound = _flight(
            airline="easyjet",
            origin="BRS", destination="BCN",
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=45.0, flight_number="GF-E-BRSBCN-0700",
        )
        return_fl = _flight(
            airline="easyjet",
            origin="BCN", destination="BRS",
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=50.0, flight_number="GF-E-BCNBRS-1800",
        )

        async def mock_search_gf(origin, destination, job):
            if origin == "BRS" and destination == "BCN":
                return [outbound]
            if origin == "BCN" and destination == "BRS":
                return [return_fl]
            return []

        async def mock_search_ryanair(origin, destination, job):
            return []  # Ryanair has no flights this day

        # Ryanair discovers BCN; Google Flights has no route discovery
        ryanair_mock = AsyncMock()
        ryanair_mock.airline_name = "ryanair"
        ryanair_mock.get_destinations = AsyncMock(return_value=["BCN"])
        ryanair_mock.search = mock_search_ryanair

        gf_mock = AsyncMock()
        gf_mock.airline_name = "googleflights"
        gf_mock.get_destinations = AsyncMock(return_value=[])
        gf_mock.search = mock_search_gf

        def mock_get_scraper(name):
            return {"ryanair": ryanair_mock, "googleflights": gf_mock}[name]

        with patch("daytrips.get_scraper", side_effect=mock_get_scraper), \
             patch("daytrips.list_scrapers",
                   return_value=["ryanair", "googleflights"]):

            results = await search_day_trips(
                origin="BRS",
                date_from=date(2025, 6, 14),
                date_to=date(2025, 6, 14),
                airlines=["googleflights"],
            )

        assert len(results) == 1
        assert results[0].outbound.airline == "easyjet"
        assert results[0].total_price == 95.0


class TestFormatDayTrip:
    def test_format(self):
        out = _flight(
            origin="BRS", destination="BCN",
            dep_date=date(2025, 6, 14),
            dep_time=time(7, 0), arr_time=time(10, 0),
            price=40.0,
        )
        ret = _flight(
            airline="wizzair",
            origin="BCN", destination="BRS",
            dep_date=date(2025, 6, 14),
            dep_time=time(18, 0), arr_time=time(21, 0),
            price=35.0,
        )
        trip = DayTripResult(outbound=out, return_flight=ret)
        text = format_day_trip(trip, 1)
        assert "Bristol (BRS) -> Barcelona (BCN)" in text
        assert "07:00" in text
        assert "18:00" in text
        assert "75.00" in text
        assert "Ryanair" in text
        assert "Wizzair" in text
