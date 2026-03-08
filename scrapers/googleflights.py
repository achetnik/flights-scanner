import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class GoogleFlightsScraper(BaseScraper):
    """Scrape flight data from Google Flights via the fast-flights library.

    Google Flights aggregates all airlines (EasyJet, Ryanair, BA, etc.)
    and returns real departure/arrival times and prices.  This scraper
    acts as a universal fallback that bypasses airline-specific bot
    protection (e.g. EasyJet's Akamai).

    Limitations
    -----------
    * No route-discovery API — ``get_destinations()`` returns ``[]``.
      Use alongside other scrapers for day-trip searches.
    * Prices may not always be in GBP depending on Google's locale
      detection.  Currency symbols are stripped; the numeric value is
      used as-is.
    * Flight numbers are synthesised (Google doesn't expose them).
    """

    airline_name = "googleflights"

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        """Search Google Flights for each day in the date range.

        ``fast-flights`` accepts a single date per query, so we iterate
        from ``date_from`` to ``date_to`` (same pattern as Ryanair).
        Each call is offloaded to a thread because ``get_flights()`` is
        synchronous.
        """
        results: List[FlightResult] = []
        current = job.date_from
        while current <= job.date_to:
            day_flights = await self._fetch_day(
                origin, destination, current, job,
            )
            results.extend(day_flights)
            current += timedelta(days=1)
        return results

    async def _fetch_day(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
    ) -> List[FlightResult]:
        """Fetch flights for a single day, wrapping the sync library."""
        try:
            raw_result = await asyncio.to_thread(
                self._call_fast_flights, origin, destination, dep_date, job,
            )
            return self._parse_result(raw_result, origin, destination, dep_date)
        except Exception as e:
            logger.warning(
                f"GoogleFlights: {origin}->{destination} on {dep_date}: {e}"
            )
            return []

    # ------------------------------------------------------------------
    # External library boundary (mocked in tests)
    # ------------------------------------------------------------------

    @staticmethod
    def _call_fast_flights(
        origin: str, destination: str, dep_date: date, job: JobConfig,
    ):
        """Synchronous call to fast-flights, executed inside a thread.

        The import is intentionally lazy so the module can be imported
        (and tested) even when ``fast-flights`` is not installed.
        """
        from fast_flights import FlightData, Passengers, get_flights

        return get_flights(
            flight_data=[
                FlightData(
                    date=dep_date.strftime("%Y-%m-%d"),
                    from_airport=origin,
                    to_airport=destination,
                ),
            ],
            trip="one-way",
            seat="economy",
            passengers=Passengers(adults=job.passengers),
            fetch_mode="local",
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_result(
        self,
        result,
        origin: str,
        destination: str,
        dep_date: date,
    ) -> List[FlightResult]:
        """Convert a fast-flights ``Result`` into ``FlightResult`` objects."""
        flights: List[FlightResult] = []
        if not result or not hasattr(result, "flights"):
            return flights

        for flight in result.flights:
            # Price
            price = self._parse_price(getattr(flight, "price", None))
            if price is None or price <= 0:
                continue

            # Airline name (real airline, not "googleflights")
            airline_name = getattr(flight, "name", "Unknown")

            # Times
            dep_time = self._parse_time(getattr(flight, "departure", None))
            arr_time = self._parse_time(getattr(flight, "arrival", None))

            # Flight number (synthesised)
            flight_number = self._synthesize_flight_number(
                airline_name, origin, destination, dep_date, dep_time,
            )

            # Booking URL
            booking_url = self._build_booking_url(
                origin, destination, dep_date,
            )

            flights.append(FlightResult(
                airline=airline_name.lower(),
                origin=origin,
                destination=destination,
                departure_date=dep_date,
                departure_time=dep_time,
                arrival_time=arr_time,
                price_gbp=price,
                booking_url=booking_url,
                flight_number=flight_number,
            ))

        return flights

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_price(price_str) -> Optional[float]:
        """Extract numeric price from ``'£65'``, ``'$120.50'``, ``89.0`` etc."""
        if price_str is None:
            return None
        if isinstance(price_str, (int, float)):
            return float(price_str)
        cleaned = re.sub(r"[^\d.]", "", str(price_str))
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _parse_time(time_str) -> Optional[time]:
        """Parse time strings from Google Flights into ``time`` objects.

        The ``fast-flights`` library may return extended formats such as
        ``'5:35 PM on Mon, Jun 15'``.  We strip the ``' on ...'`` suffix
        before attempting the standard 12h / 24h parse.
        """
        if time_str is None:
            return None
        time_str = str(time_str).strip()
        # Strip extended suffix: "5:35 PM on Mon, Jun 15" → "5:35 PM"
        time_str = re.sub(r"\s+on\s+.*$", "", time_str, flags=re.IGNORECASE)
        # 12-hour formats
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                return datetime.strptime(time_str, fmt).time()
            except ValueError:
                continue
        # 24-hour formats
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(time_str, fmt).time()
            except ValueError:
                continue
        return None

    @staticmethod
    def _synthesize_flight_number(
        airline_name: str,
        origin: str,
        destination: str,
        dep_date: date,
        dep_time: Optional[time],
    ) -> str:
        """Create a pseudo flight number for dedup fingerprinting.

        Format: ``GF-RA-BRSBCN-0630``  (initials-route-time).
        """
        words = airline_name.split()
        initials = "".join(w[0].upper() for w in words if w)[:2] or "XX"
        time_part = dep_time.strftime("%H%M") if dep_time else "0000"
        return f"GF-{initials}-{origin}{destination}-{time_part}"

    @staticmethod
    def _build_booking_url(
        origin: str, destination: str, dep_date: date,
    ) -> str:
        """Return a Google Flights search URL."""
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.google.com/travel/flights"
            f"?q=flights+from+{origin}+to+{destination}+on+{d}"
        )
