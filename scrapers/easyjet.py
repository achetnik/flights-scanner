import asyncio
import httpx
import logging
from datetime import date, datetime, time
from typing import List, Optional

from playwright.async_api import async_playwright
from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

EASYJET_API_URL = (
    "https://www.easyjet.com/ejavailability/api/v16/availability/query"
)
EASYJET_ROUTES_URL = (
    "https://www.easyjet.com/ejcms/cache/route-cards/{origin}"
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


COOKIE_TTL_SECONDS = 600  # cache Playwright cookies for 10 minutes


class EasyJetScraper(BaseScraper):
    airline_name = "easyjet"

    # Sentinel to distinguish "never fetched" from "fetched but empty"
    _NOT_FETCHED = object()

    def __init__(self):
        super().__init__()
        self._cached_cookies = self._NOT_FETCHED
        self._cookies_fetched_at: Optional[datetime] = None
        self._cookie_lock = asyncio.Lock()

    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        cookies = await self._get_session_cookies()
        if not cookies:
            # Playwright failed to get cookies — skip search entirely
            # to avoid dozens of doomed requests timing out against Akamai.
            logger.info(
                f"EasyJet: skipping {origin}->{destination} (no session cookies)"
            )
            return []
        results = []
        current = job.date_from
        while current <= job.date_to:
            flights = await self._fetch_day(
                origin, destination, current, job, cookies,
            )
            results.extend(flights)
            current = current + __import__("datetime").timedelta(days=1)
        return results

    async def _get_session_cookies(self) -> dict:
        """Return Akamai session cookies, using a cache to avoid repeated Playwright launches.

        Cookies are cached for up to COOKIE_TTL_SECONDS (10 min).  An
        asyncio.Lock prevents multiple concurrent callers from all spawning
        their own browser — only the first one fetches, the rest wait and
        then share the cached result.
        """
        async with self._cookie_lock:
            # Check cache under lock
            if self._cached_cookies is not self._NOT_FETCHED and self._cookies_fetched_at is not None:
                age = (datetime.now() - self._cookies_fetched_at).total_seconds()
                if age < COOKIE_TTL_SECONDS:
                    return self._cached_cookies

            # Cache miss — launch Playwright once.
            # Cache the result whether it's empty or not: if Playwright
            # fails (e.g. missing system deps), retrying 40+ times in the
            # same session won't help and just fills the logs.
            cookies = await self._fetch_cookies_via_playwright()
            self._cached_cookies = cookies
            self._cookies_fetched_at = datetime.now()
            return cookies

    async def _fetch_cookies_via_playwright(self) -> dict:
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
            async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
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
                price_gbp=price,
                booking_url=self._build_booking_url(origin, destination, dep_dt.date()),
                flight_number=flight_number,
            ))
        return results

    async def get_destinations(self, origin: str) -> List[str]:
        """Discover destinations from *origin* via EasyJet route-cards API.

        Falls back to an empty list if the endpoint is blocked by Akamai or
        returns an unexpected format.  The day-trips module has its own
        fallback that searches all known destinations for airlines without
        route discovery, so this is best-effort.
        """
        url = EASYJET_ROUTES_URL.format(origin=origin)
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            destinations = []
            # Response is a list of route objects with an "iata" field
            items = data if isinstance(data, list) else data.get("routes", [])
            for item in items:
                iata = (
                    item.get("iata")
                    or item.get("arrivalAirportCode")
                    or item.get("ArrivalIata")
                )
                if iata and isinstance(iata, str) and len(iata) == 3:
                    destinations.append(iata.upper())
            return destinations
        except Exception as e:
            logger.warning(f"EasyJet: route discovery failed for {origin}: {e}")
            return []

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.easyjet.com/en/cheap-flights/{origin.lower()}"
            f"/{destination.lower()}?departDate={d}&adults=1"
        )
