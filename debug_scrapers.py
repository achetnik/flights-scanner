#!/usr/bin/env python3
"""Quick diagnostic script to test Wizzair & EasyJet APIs directly.

Usage:
    python debug_scrapers.py
"""
import asyncio
import httpx
import json
import sys
from datetime import date, timedelta

# ── Wizzair ──────────────────────────────────────────────────────

WIZZAIR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://wizzair.com",
    "Referer": "https://wizzair.com/",
}


async def wizzair_get_version() -> str:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        r = await client.get(
            "https://www.wizzair.com/buildnumber",
            headers={"User-Agent": WIZZAIR_HEADERS["User-Agent"]},
        )
        r.raise_for_status()
        text = r.text.strip()
        parts = text.split("/")
        for i, part in enumerate(parts):
            if "be.wizzair.com" in part and i + 1 < len(parts):
                return parts[i + 1]
    raise ValueError(f"Could not parse version from: {text}")


async def wizzair_get_destinations(version: str, origin: str):
    url = f"https://be.wizzair.com/{version}/Api/asset/map?languageCode=en-gb"
    async with httpx.AsyncClient(headers=WIZZAIR_HEADERS, timeout=15, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    for city in data.get("cities", []):
        if city.get("iata") == origin:
            conns = [c["iata"] for c in city.get("connections", [])]
            return conns
    return []


async def wizzair_test_search(version: str, origin: str, dest: str, dep_date: date):
    url = f"https://be.wizzair.com/{version}/Api/search/search"
    payload = {
        "flightList": [
            {
                "departureStation": origin,
                "arrivalStation": dest,
                "departureDate": dep_date.strftime("%Y-%m-%d"),
            }
        ],
        "adultCount": 1,
        "childCount": 0,
        "infantCount": 0,
        "wdc": True,
    }
    async with httpx.AsyncClient(headers=WIZZAIR_HEADERS, timeout=30, follow_redirects=True) as client:
        r = await client.post(url, json=payload)
        return r.status_code, r.text[:500]


async def wizzair_test_timetable(version: str, origin: str, dest: str, dep_date: date):
    url = f"https://be.wizzair.com/{version}/Api/search/timetable"
    payload = {
        "flightList": [
            {
                "departureStation": origin,
                "arrivalStation": dest,
                "from": dep_date.strftime("%Y-%m-%dT00:00:00"),
                "to": dep_date.strftime("%Y-%m-%dT00:00:00"),
            }
        ],
        "priceType": "regular",
        "adultCount": 1,
        "childCount": 0,
        "infantCount": 0,
    }
    async with httpx.AsyncClient(headers=WIZZAIR_HEADERS, timeout=30, follow_redirects=True) as client:
        r = await client.post(url, json=payload)
        return r.status_code, r.text[:500]


async def debug_wizzair():
    print("=" * 60)
    print("WIZZAIR DIAGNOSTICS")
    print("=" * 60)

    # 1. Version
    try:
        version = await wizzair_get_version()
        print(f"✅ API version: {version}")
    except Exception as e:
        print(f"❌ Failed to get version: {e}")
        return

    # 2. Destinations from BRS
    origin = "BRS"
    try:
        dests = await wizzair_get_destinations(version, origin)
        print(f"✅ Destinations from {origin}: {dests}")
    except Exception as e:
        print(f"❌ Route discovery failed: {e}")
        dests = []

    if not dests:
        # Try LTN as a known Wizzair hub
        origin = "LTN"
        print(f"   Trying {origin} instead...")
        try:
            dests = await wizzair_get_destinations(version, origin)
            print(f"✅ Destinations from {origin}: {dests[:10]}... ({len(dests)} total)")
        except Exception as e:
            print(f"❌ Route discovery failed: {e}")
            return

    dest = dests[0] if dests else "BUD"

    # 3. Test with different dates
    today = date.today()
    near_date = today + timedelta(days=14)   # 2 weeks out
    far_date = today + timedelta(days=300)   # ~10 months out

    print(f"\n--- Testing {origin} -> {dest} ---")

    # Search endpoint
    for label, d in [("near future (2 weeks)", near_date), ("far future (10 months)", far_date)]:
        try:
            status, body = await wizzair_test_search(version, origin, dest, d)
            print(f"\n  Search [{label}] {d}: HTTP {status}")
            if status == 200:
                data = json.loads(body)
                flights = data.get("outboundFlights", [])
                print(f"  ✅ {len(flights)} outbound flights found")
                if flights:
                    f = flights[0]
                    print(f"     First: {f.get('departureDateTime')} -> {f.get('arrivalDateTime')}")
            else:
                print(f"  ❌ {body[:200]}")
        except Exception as e:
            print(f"  ❌ Search error: {e}")

    # Timetable endpoint
    for label, d in [("near future (2 weeks)", near_date), ("far future (10 months)", far_date)]:
        try:
            status, body = await wizzair_test_timetable(version, origin, dest, d)
            print(f"\n  Timetable [{label}] {d}: HTTP {status}")
            if status == 200:
                data = json.loads(body)
                flights = data.get("outboundFlights", [])
                print(f"  ✅ {len(flights)} outbound flights found")
                if flights:
                    f = flights[0]
                    print(f"     Price: {f.get('price')}, Dates: {f.get('departureDates', [])[:3]}")
            else:
                print(f"  ❌ {body[:200]}")
        except Exception as e:
            print(f"  ❌ Timetable error: {e}")


# ── EasyJet ──────────────────────────────────────────────────────

EASYJET_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def easyjet_test_routes(origin: str):
    url = f"https://www.easyjet.com/ejcms/cache/route-cards/{origin}"
    async with httpx.AsyncClient(headers=EASYJET_HEADERS, timeout=15, follow_redirects=True) as client:
        r = await client.get(url)
        return r.status_code, r.text[:500]


async def easyjet_test_availability(origin: str, dest: str, dep_date: date, cookies: dict = None):
    params = {
        "AdditionalSeats": 0,
        "AdultSeats": 1,
        "ArrivalIata": dest,
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
    headers = {**EASYJET_HEADERS}
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers["Cookie"] = cookie_str
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        r = await client.get(
            "https://www.easyjet.com/ejavailability/api/v16/availability/query",
            params=params,
        )
        return r.status_code, r.text[:500]


async def easyjet_get_cookies():
    """Try to get Akamai session cookies via Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  ⚠️  playwright not installed, skipping cookie fetch")
        return {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=EASYJET_HEADERS["User-Agent"],
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            print("  Launching headless browser...")
            await page.goto("https://www.easyjet.com/en/", wait_until="load", timeout=30000)
            await page.wait_for_timeout(5000)
            cookies = await context.cookies()
            await browser.close()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            print(f"  ✅ Got {len(cookie_dict)} cookies")
            # Show the important ones
            important = ["_abck", "ak_bmsc", "bm_sv", "bm_sz"]
            for key in important:
                if key in cookie_dict:
                    print(f"     {key}: {cookie_dict[key][:30]}...")
            return cookie_dict
    except Exception as e:
        print(f"  ❌ Playwright failed: {e}")
        return {}


async def debug_easyjet():
    print("\n" + "=" * 60)
    print("EASYJET DIAGNOSTICS")
    print("=" * 60)

    origin = "BRS"
    dest = "BCN"
    dep_date = date.today() + timedelta(days=14)

    # 1. Route discovery
    print(f"\n--- Route discovery for {origin} ---")
    try:
        status, body = await easyjet_test_routes(origin)
        print(f"  HTTP {status}")
        if status == 200:
            data = json.loads(body)
            if isinstance(data, list):
                iatas = [d.get("iata", "?") for d in data[:10]]
                print(f"  ✅ Routes: {iatas}... ({len(data)} total)")
            else:
                print(f"  Response: {body[:200]}")
        else:
            print(f"  ❌ {body[:200]}")
    except Exception as e:
        print(f"  ❌ {e}")

    # 2. Availability WITHOUT cookies
    print(f"\n--- Availability {origin}->{dest} on {dep_date} (no cookies) ---")
    try:
        status, body = await easyjet_test_availability(origin, dest, dep_date)
        print(f"  HTTP {status}")
        if status == 200:
            data = json.loads(body)
            flights = data.get("Flights", [])
            print(f"  ✅ {len(flights)} flights found")
        else:
            print(f"  ❌ {body[:200]}")
    except Exception as e:
        print(f"  ❌ {e}")

    # 3. Get cookies via Playwright
    print(f"\n--- Playwright cookie fetch ---")
    cookies = await easyjet_get_cookies()

    # 4. Availability WITH cookies
    if cookies:
        print(f"\n--- Availability {origin}->{dest} on {dep_date} (with cookies) ---")
        try:
            status, body = await easyjet_test_availability(origin, dest, dep_date, cookies)
            print(f"  HTTP {status}")
            if status == 200:
                data = json.loads(body)
                flights = data.get("Flights", [])
                print(f"  ✅ {len(flights)} flights found")
                if flights:
                    f = flights[0]
                    print(f"     First: {f.get('FlightNumber')} {f.get('DepartureDateTime')} -> {f.get('ArrivalDateTime')}")
                    print(f"     Price: {f.get('Prices', [{}])}")
            else:
                print(f"  ❌ {body[:200]}")
        except Exception as e:
            print(f"  ❌ {e}")
    else:
        print("\n  ⚠️  Skipping cookie-authenticated test (no cookies)")


async def main():
    await debug_wizzair()
    await debug_easyjet()
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
