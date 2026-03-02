import httpx
from datetime import date, datetime
from typing import List, Optional

from playwright.async_api import async_playwright
from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

WIZZAIR_API_URL = "https://be.wizzair.com/24.2.0/Api/search/timetable"
WIZZAIR_HOME = "https://wizzair.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}


class WizzairScraper(BaseScraper):
    airline_name = "wizzair"

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        cookie = await self._get_session_cookie()
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
        headers = {**HEADERS, "Cookie": f"wdc={cookie}"}
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            response = await client.post(WIZZAIR_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        return self._parse_response(data, origin, destination)

    async def _get_session_cookie(self) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(WIZZAIR_HOME, wait_until="networkidle", timeout=30000)
            cookies = await page.context.cookies()
            await browser.close()
            for c in cookies:
                if c["name"] == "wdc":
                    return c["value"]
        return ""

    def _parse_response(self, data: dict, origin: str, destination: str) -> List[FlightResult]:
        results = []
        for flight in data.get("outboundFlights", []):
            price_info = flight.get("price", {})
            price_eur = price_info.get("amount", 0)
            if price_eur <= 0:
                continue
            departure_dates = flight.get("departureDates", [])
            flight_numbers = flight.get("flightNumbers", [""])
            for dep_str in departure_dates:
                dep_date = datetime.strptime(dep_str[:10], "%Y-%m-%d").date()
                flight_number = flight_numbers[0] if flight_numbers else "W?"
                results.append(FlightResult(
                    airline="wizzair",
                    origin=origin,
                    destination=destination,
                    departure_date=dep_date,
                    price_eur=price_eur,
                    booking_url=self._build_booking_url(origin, destination, dep_date),
                    flight_number=flight_number,
                ))
        return results

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://wizzair.com/en-gb/flights/{origin.lower()}/{destination.lower()}/{d}/null/2/0/0/null"
        )
