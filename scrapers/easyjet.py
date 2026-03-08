import httpx
import logging
from datetime import date, datetime, time
from typing import List

from playwright.async_api import async_playwright
from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

EASYJET_API_URL = (
    "https://www.easyjet.com/ejavailability/api/v16/availability/query"
)
EASYJET_HOME = "https://www.easyjet.com/en/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

logger = logging.getLogger(__name__)


class EasyJetScraper(BaseScraper):
    airline_name = "easyjet"

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        results = []
        cookies = await self._get_session_cookies()
        current = job.date_from
        while current <= job.date_to:
            flights = await self._fetch_day(
                origin, destination, current, job, cookies,
            )
            results.extend(flights)
            current = current + __import__("datetime").timedelta(days=1)
        return results

    async def _get_session_cookies(self) -> dict:
        """Load EasyJet homepage via Playwright to obtain Akamai session cookies."""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                )
                page = await context.new_page()
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                await page.goto(EASYJET_HOME, wait_until="load", timeout=30000)
                await page.wait_for_timeout(3000)
                cookies = await context.cookies()
                await browser.close()
                return {c["name"]: c["value"] for c in cookies}
        except Exception as e:
            logger.warning(f"EasyJet: failed to get session cookies: {e}")
            return {}

    async def _fetch_day(
        self,
        origin: str,
        destination: str,
        dep_date: date,
        job: JobConfig,
        cookies: dict,
    ) -> List[FlightResult]:
        params = {
            "AdditionalSeats": 0,
            "AdultSeats": job.passengers,
            "ArrivalIata": destination,
            "ChildSeats": 0,
            "DepartureIata": origin,
            "IncludeAdminFees": "true",
            "IncludeFlexiFares": "false",
            "IncludeLowestFareSeats": "true",
            "IncludePrices": "true",
            "Infants": 0,
            "IsTransfer": "false",
            "DepartureDate": dep_date.strftime("%Y-%m-%d"),
        }
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {**HEADERS}
        if cookie_str:
            headers["Cookie"] = cookie_str

        try:
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                response = await client.get(EASYJET_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
            return self._parse_response(data, origin, destination)
        except httpx.TimeoutException:
            logger.warning(
                f"EasyJet: request timed out for {origin}->{destination} on {dep_date} "
                "(likely blocked by Akamai bot protection)"
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"EasyJet: HTTP {e.response.status_code} for {origin}->{destination} "
                f"on {dep_date}"
            )
            return []

    def _parse_response(
        self, data: dict, origin: str, destination: str,
    ) -> List[FlightResult]:
        results = []
        for flight in data.get("Flights", []):
            dep_str = flight.get("DepartureDateTime", "")
            arr_str = flight.get("ArrivalDateTime", "")
            if not dep_str:
                continue
            dep_dt = datetime.strptime(dep_str[:19], "%Y-%m-%dT%H:%M:%S")
            arr_dt = (
                datetime.strptime(arr_str[:19], "%Y-%m-%dT%H:%M:%S")
                if arr_str
                else None
            )
            # Price may be in Prices list or direct Amount field
            prices = flight.get("Prices", [])
            price = 0.0
            if prices:
                for p in prices:
                    if p.get("FareType") == "Standard" or not price:
                        price = p.get("Amount", 0)
            else:
                price = flight.get("Price", 0)
            if price <= 0:
                continue
            flight_number = flight.get("FlightNumber", "")
            results.append(FlightResult(
                airline="easyjet",
                origin=origin,
                destination=destination,
                departure_date=dep_dt.date(),
                departure_time=dep_dt.time(),
                arrival_time=arr_dt.time() if arr_dt else None,
                price_eur=price,
                booking_url=self._build_booking_url(origin, destination, dep_dt.date()),
                flight_number=flight_number,
            ))
        return results

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.easyjet.com/en/cheap-flights/{origin.lower()}"
            f"/{destination.lower()}?departDate={d}&adults=1"
        )
