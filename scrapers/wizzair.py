import asyncio
import httpx
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

WIZZAIR_BUILDNUMBER_URL = "https://www.wizzair.com/buildnumber"
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
        """Search for flights using the timetable endpoint.

        Makes ONE API call covering the entire date range (the timetable
        endpoint returns all dates with prices in a single response).
        This is far more efficient than one call per day.
        """
        version = await self._ensure_version()
        return await self._fetch_timetable(
            origin, destination, job.date_from, job.date_to, job, version,
        )

    async def _fetch_timetable(
        self,
        origin: str,
        destination: str,
        date_from: date,
        date_to: date,
        job: JobConfig,
        version: str,
    ) -> List[FlightResult]:
        url = WIZZAIR_TIMETABLE_TEMPLATE.format(version=version)
        payload = {
            "flightList": [
                {
                    "departureStation": origin,
                    "arrivalStation": destination,
                    "from": date_from.strftime("%Y-%m-%dT00:00:00"),
                    "to": date_to.strftime("%Y-%m-%dT00:00:00"),
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
            logger.warning(
                f"Wizzair: {origin}->{destination} "
                f"({date_from} to {date_to}): {e}"
            )
            return []

    def _parse_timetable_response(
        self, data: dict, origin: str, destination: str,
    ) -> List[FlightResult]:
        """Parse the timetable response, estimating arrival times.

        Each entry in ``outboundFlights`` contains a price and a list of
        departure date-times.  We estimate arrival = departure + 3 h.
        """
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
