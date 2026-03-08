import httpx
import logging
from datetime import date, datetime, time
from typing import List

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

WIZZAIR_BUILDNUMBER_URL = "https://wizzair.com/buildnumber"
WIZZAIR_API_TEMPLATE = "https://be.wizzair.com/{version}/Api/search/timetable"
WIZZAIR_MAP_TEMPLATE = "https://be.wizzair.com/{version}/Api/asset/map?languageCode=en-gb"

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

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        version = await self._get_api_version()
        url = WIZZAIR_API_TEMPLATE.format(version=version)
        payload = {
            "flightList": [
                {
                    "departureStation": origin,
                    "arrivalStation": destination,
                    "from": job.date_from.strftime("%Y-%m-%dT00:00:00"),
                    "to": job.date_to.strftime("%Y-%m-%dT00:00:00"),
                }
            ],
            "priceType": "regular",
            "adultCount": job.passengers,
            "childCount": 0,
            "infantCount": 0,
        }
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return self._parse_response(data, origin, destination)

    async def _get_api_version(self) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
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

    def _parse_response(self, data: dict, origin: str, destination: str) -> List[FlightResult]:
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
                dep_date = dep_dt.date()
                dep_time = dep_dt.time()
                # Use station pair + datetime as flight identifier
                flight_number = f"W6-{dep_station}{arr_station}-{dep_str[:16]}"
                results.append(FlightResult(
                    airline="wizzair",
                    origin=dep_station,
                    destination=arr_station,
                    departure_date=dep_date,
                    departure_time=dep_time,
                    price_eur=price,
                    booking_url=self._build_booking_url(
                        dep_station, arr_station, dep_date, job_passengers=1,
                    ),
                    flight_number=flight_number,
                ))
        return results

    async def get_destinations(self, origin: str) -> List[str]:
        version = await self._get_api_version()
        url = WIZZAIR_MAP_TEMPLATE.format(version=version)
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
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
