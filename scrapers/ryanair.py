import httpx
from datetime import date, datetime, timedelta
from typing import List

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

RYANAIR_AVAILABILITY_URL = "https://www.ryanair.com/api/booking/v4/availability"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


class RyanairScraper(BaseScraper):
    airline_name = "ryanair"

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
        date_out: date,
        job: JobConfig,
    ) -> List[FlightResult]:
        params = {
            "ADT": job.passengers,
            "CHD": 0,
            "DateOut": date_out.strftime("%Y-%m-%d"),
            "Destination": destination,
            "FlexDaysOut": 0,
            "INF": 0,
            "Origin": origin,
            "TEEN": 0,
            "ToUs": "AGREED",
            "IncludeConnectingFlights": "false",
        }

        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.get(RYANAIR_AVAILABILITY_URL, params=params)
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data, origin, destination)

    def _parse_response(self, data: dict, origin: str, destination: str) -> List[FlightResult]:
        results = []
        for trip in data.get("trips", []):
            for day in trip.get("dates", []):
                date_str = day.get("dateOut", "")[:10]
                if not date_str:
                    continue
                dep_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                for flight in day.get("flights", []):
                    fares = flight.get("regularFare", {}).get("fares", [])
                    if not fares:
                        continue
                    price = fares[0].get("amount", 0)
                    if price <= 0:
                        continue
                    flight_number = flight.get("flightNumber", "")
                    booking_url = self._build_booking_url(origin, destination, dep_date)
                    results.append(FlightResult(
                        airline="ryanair",
                        origin=origin,
                        destination=destination,
                        departure_date=dep_date,
                        price_eur=price,
                        booking_url=booking_url,
                        flight_number=flight_number,
                    ))
        return results

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.ryanair.com/en/gb/trip/flights/select"
            f"?adults=2&teens=0&children=0&infants=0"
            f"&dateOut={d}&isReturn=false"
            f"&originIata={origin}&destinationIata={destination}"
        )
