import asyncio
import httpx
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

WIZZAIR_BUILDNUMBER_URL = "https://www.wizzair.com/buildnumber"
WIZZAIR_SEARCH_TEMPLATE = "https://be.wizzair.com/{version}/Api/search/search"
WIZZAIR_TIMETABLE_TEMPLATE = "https://be.wizzair.com/{version}/Api/search/timetable"
WIZZAIR_MAP_TEMPLATE = "https://be.wizzair.com/{version}/Api/asset/map?languageCode=en-gb"

# Estimated flight duration used when the timetable endpoint (which lacks
# arrival times) is the only data source.  3 hours is a conservative
# estimate for Wizzair's European short-haul network.
ESTIMATED_FLIGHT_HOURS = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://wizzair.com",
    "Referer": "https://wizzair.com/",
}

logger = logging.getLogger(__name__)


class WizzairScraper(BaseScraper):
    airline_name = "wizzair"

    def __init__(self):
        super().__init__()
        # Tracks whether the search endpoint has been proven to work.
        # None = untested, True = works, False = failed on first attempt.
        self._search_works: Optional[bool] = None
        # Cache the API version so we don't fetch it for every destination.
        self._cached_version: Optional[str] = None
        # Lock prevents concurrent coroutines from all fetching the version
        self._version_lock = asyncio.Lock()

    async def _ensure_version(self) -> str:
        """Return cached API version, fetching once under lock."""
        async with self._version_lock:
            if not self._cached_version:
                self._cached_version = await self._get_api_version()
            return self._cached_version

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        results = []
        version = await self._ensure_version()
        current = job.date_from
        while current <= job.date_to:
            flights = await self._fetch_day(origin, destination, current, job, version)
            results.extend(flights)
            current = current + timedelta(days=1)
        return results

    async def _fetch_day(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
        version: str,
    ) -> List[FlightResult]:
        # If the search endpoint hasn't been proven broken, try it first
        # (it returns arrival times which we need for day-trip qualification).
        if self._search_works is not False:
            flights = await self._try_search_endpoint(
                origin, destination, dep_date, job, version,
            )
            if flights:
                self._search_works = True
                return flights
            # First failure — mark search as broken so we skip it next time
            if self._search_works is None:
                logger.info(
                    "Wizzair: search endpoint returned no results, "
                    "falling back to timetable + estimated arrival times"
                )
                self._search_works = False

        # Fallback: timetable endpoint (works reliably but lacks arrival times,
        # so we estimate them).
        return await self._try_timetable_endpoint(
            origin, destination, dep_date, job, version,
        )

    # ------------------------------------------------------------------
    # Search endpoint (preferred — includes arrival times)
    # ------------------------------------------------------------------

    async def _try_search_endpoint(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
        version: str,
    ) -> List[FlightResult]:
        url = WIZZAIR_SEARCH_TEMPLATE.format(version=version)
        payload = {
            "flightList": [
                {
                    "departureStation": origin,
                    "arrivalStation": destination,
                    "departureDate": dep_date.strftime("%Y-%m-%d"),
                }
            ],
            "adultCount": job.passengers,
            "childCount": 0,
            "infantCount": 0,
            "wdc": True,
        }
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            return self._parse_search_response(data, origin, destination)
        except Exception as e:
            logger.debug(f"Wizzair search endpoint: {origin}->{destination} on {dep_date}: {e}")
            return []

    def _parse_search_response(
        self, data: dict, origin: str, destination: str,
    ) -> List[FlightResult]:
        """Parse the /Api/search/search response which includes arrival times."""
        results = []
        for flight in data.get("outboundFlights", []):
            dep_str = flight.get("departureDateTime", "")
            arr_str = flight.get("arrivalDateTime", "")
            if not dep_str:
                continue
            dep_dt = datetime.strptime(dep_str[:19], "%Y-%m-%dT%H:%M:%S")
            arr_dt = (
                datetime.strptime(arr_str[:19], "%Y-%m-%dT%H:%M:%S")
                if arr_str
                else None
            )
            # Get cheapest fare from fares array
            fares = flight.get("fares", [])
            price = 0.0
            for fare in fares:
                discounted = fare.get("discountedPrice", {}).get("amount", 0)
                base = fare.get("basePrice", {}).get("amount", 0)
                fare_price = discounted if discounted > 0 else base
                if fare_price > 0 and (price == 0 or fare_price < price):
                    price = fare_price
            if price <= 0:
                continue
            dep_station = flight.get("departureStation", origin)
            arr_station = flight.get("arrivalStation", destination)
            flight_number = flight.get(
                "flightNumber",
                f"W6-{dep_station}{arr_station}-{dep_str[:16]}",
            )
            results.append(FlightResult(
                airline="wizzair",
                origin=dep_station,
                destination=arr_station,
                departure_date=dep_dt.date(),
                departure_time=dep_dt.time(),
                arrival_time=arr_dt.time() if arr_dt else None,
                price_gbp=price,
                booking_url=self._build_booking_url(
                    dep_station, arr_station, dep_dt.date(), job_passengers=1,
                ),
                flight_number=flight_number,
            ))
        return results

    # ------------------------------------------------------------------
    # Timetable endpoint (fallback — reliable but no arrival times)
    # ------------------------------------------------------------------

    async def _try_timetable_endpoint(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
        version: str,
    ) -> List[FlightResult]:
        url = WIZZAIR_TIMETABLE_TEMPLATE.format(version=version)
        payload = {
            "flightList": [
                {
                    "departureStation": origin,
                    "arrivalStation": destination,
                    "from": dep_date.strftime("%Y-%m-%dT00:00:00"),
                    "to": dep_date.strftime("%Y-%m-%dT00:00:00"),
                }
            ],
            "priceType": "regular",
            "adultCount": job.passengers,
            "childCount": 0,
            "infantCount": 0,
        }
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            return self._parse_timetable_response(data, origin, destination)
        except Exception as e:
            logger.warning(f"Wizzair: {origin}->{destination} on {dep_date}: {e}")
            return []

    def _parse_timetable_response(
        self, data: dict, origin: str, destination: str,
    ) -> List[FlightResult]:
        """Parse the timetable response, estimating arrival times."""
        results = []
        for flight in data.get("outboundFlights", []):
            price_info = flight.get("price", {})
            price = price_info.get("amount", 0)
            if price <= 0:
                continue
            departure_dates = flight.get("departureDates", [])
            dep_station = flight.get("departureStation", origin)
            arr_station = flight.get("arrivalStation", destination)
            for dep_str in departure_dates:
                dep_dt = datetime.strptime(dep_str[:19], "%Y-%m-%dT%H:%M:%S")
                # Estimate arrival: departure + ESTIMATED_FLIGHT_HOURS
                est_arrival = dep_dt + timedelta(hours=ESTIMATED_FLIGHT_HOURS)
                flight_number = f"W6-{dep_station}{arr_station}-{dep_str[:16]}"
                results.append(FlightResult(
                    airline="wizzair",
                    origin=dep_station,
                    destination=arr_station,
                    departure_date=dep_dt.date(),
                    departure_time=dep_dt.time(),
                    arrival_time=est_arrival.time(),
                    price_gbp=price,
                    booking_url=self._build_booking_url(
                        dep_station, arr_station, dep_dt.date(), job_passengers=1,
                    ),
                    flight_number=flight_number,
                ))
        return results

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _get_api_version(self) -> str:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(WIZZAIR_BUILDNUMBER_URL, headers={
                "User-Agent": HEADERS["User-Agent"],
            })
            response.raise_for_status()
            # Response format: "SSR https://be.wizzair.com/28.1.0"
            text = response.text.strip()
            # Extract version from URL in the response
            parts = text.split("/")
            # URL is https://be.wizzair.com/28.1.0 — version is after the domain
            for i, part in enumerate(parts):
                if "be.wizzair.com" in part and i + 1 < len(parts):
                    return parts[i + 1]
        raise ValueError("Could not determine Wizzair API version")

    async def get_destinations(self, origin: str) -> List[str]:
        version = await self._ensure_version()
        url = WIZZAIR_MAP_TEMPLATE.format(version=version)
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        for city in data.get("cities", []):
            if city.get("iata") == origin:
                return [c["iata"] for c in city.get("connections", [])]
        return []

    def _build_booking_url(
        self, origin: str, destination: str, dep_date: date, job_passengers: int = 1,
    ) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://wizzair.com/en-gb/flights/{origin.lower()}/{destination.lower()}"
            f"/{d}/null/{job_passengers}/0/0/null"
        )
