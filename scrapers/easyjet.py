import httpx
from datetime import date, datetime, timedelta
from typing import List

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

EASYJET_API_URL = "https://www.easyjet.com/api/routepricing/v2/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


class EasyJetScraper(BaseScraper):
    airline_name = "easyjet"

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        results = []
        current = job.date_from
        while current <= job.date_to:
            flights = await self._fetch_day(origin, destination, current, job)
            results.extend(flights)
            current = current + timedelta(days=1)
        return results

    async def _fetch_day(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
    ) -> List[FlightResult]:
        params = {
            "originIata": origin,
            "destinationIata": destination,
            "departureDate": dep_date.strftime("%Y-%m-%d"),
            "adults": job.passengers,
            "children": 0,
            "infants": 0,
        }
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.get(EASYJET_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        return self._parse_response(data, origin, destination)

    def _parse_response(self, data: dict, origin: str, destination: str) -> List[FlightResult]:
        results = []
        for flight in data.get("outboundFlights", []):
            dep_str = flight.get("departureDateTime", "")[:10]
            if not dep_str:
                continue
            dep_date = datetime.strptime(dep_str, "%Y-%m-%d").date()
            price_eur = flight.get("priceInEur", 0) / 100
            if price_eur <= 0:
                continue
            flight_id = flight.get("id", "")
            booking_url = self._build_booking_url(origin, destination, dep_date)
            results.append(FlightResult(
                airline="easyjet",
                origin=origin,
                destination=destination,
                departure_date=dep_date,
                price_eur=price_eur,
                booking_url=booking_url,
                flight_number=flight_id,
            ))
        return results

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.easyjet.com/en/cheap-flights/{origin.lower()}/{destination.lower()}"
            f"?departDate={d}&adults=2"
        )
