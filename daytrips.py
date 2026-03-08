"""Extreme Day Trips — find the cheapest same-day return flights.

Rules:
* Outbound must **arrive** at the destination before 12:00 midday.
* Return must **depart** from the destination after 16:00.
* 1 adult passenger.
* Same home airport and same destination airport for both legs.
* Outbound and return airlines may differ.
* Searches all reachable destinations from the home airport.
* Results sorted by cheapest combined round-trip price.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Dict, List, Optional

from models import FlightResult, JobConfig
from scrapers.base import BaseScraper
from scrapers.registry import get_scraper, list_scrapers

logger = logging.getLogger(__name__)

MIDDAY = time(12, 0)
AFTERNOON = time(16, 0)


@dataclass
class DayTripResult:
    """A matched outbound + return pair for an extreme day trip."""

    outbound: FlightResult
    return_flight: FlightResult
    total_price: float = field(init=False)

    def __post_init__(self):
        self.total_price = self.outbound.price_eur + self.return_flight.price_eur


async def _discover_destinations(
    origin: str,
    airlines: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Return {airline: [destination IATA codes]} reachable from *origin*."""
    if airlines is None:
        airlines = list_scrapers()
    results: Dict[str, List[str]] = {}
    for airline in airlines:
        try:
            scraper = get_scraper(airline)
            dests = await scraper.get_destinations(origin)
            if dests:
                results[airline] = dests
        except Exception as e:
            logger.warning(f"Route discovery failed for {airline}: {e}")
    return results


def _qualifies_outbound(flight: FlightResult) -> bool:
    """Outbound must arrive before midday."""
    if flight.arrival_time is None:
        return False
    return flight.arrival_time < MIDDAY


def _qualifies_return(flight: FlightResult) -> bool:
    """Return must depart after 16:00."""
    if flight.departure_time is None:
        return False
    return flight.departure_time >= AFTERNOON


async def _fetch_flights_for_day(
    scraper: BaseScraper,
    origin: str,
    destination: str,
    day: date,
) -> List[FlightResult]:
    """Search a single airline for flights on a single day."""
    job = JobConfig(
        origin=origin,
        destinations=[destination],
        airlines=[scraper.airline_name],
        date_from=day,
        date_to=day,
        passengers=1,
    )
    try:
        return await scraper.search(origin, destination, job)
    except Exception as e:
        logger.warning(
            f"{scraper.airline_name} {origin}->{destination} on {day}: {e}"
        )
        return []


async def search_day_trips(
    origin: str,
    date_from: date,
    date_to: date,
    airlines: Optional[List[str]] = None,
) -> List[DayTripResult]:
    """Search for extreme day trips and return results sorted by price.

    Parameters
    ----------
    origin : str
        Home airport IATA code (e.g. "BRS").
    date_from, date_to : date
        Inclusive date range to search.
    airlines : list[str] | None
        Airline keys to search. ``None`` means all registered scrapers.

    Returns
    -------
    list[DayTripResult]
        Matched day trips sorted cheapest first.
    """
    if airlines is None:
        airlines = list_scrapers()

    # 1. Discover destinations reachable from origin across all airlines
    airline_dests = await _discover_destinations(origin, airlines)
    # Build a union of all destinations
    all_destinations = set()
    for dests in airline_dests.values():
        all_destinations.update(dests)

    if not all_destinations:
        logger.info(f"No destinations found from {origin}")
        return []

    logger.info(
        f"Day trips: {origin} -> {len(all_destinations)} destinations, "
        f"{date_from} to {date_to}, airlines: {airlines}"
    )

    # 2. For each day in the range, fetch flights from all airlines
    scrapers = []
    for airline in airlines:
        try:
            scrapers.append(get_scraper(airline))
        except ValueError:
            continue

    results: List[DayTripResult] = []
    current = date_from
    while current <= date_to:
        day = current
        current += timedelta(days=1)

        # Collect outbound flights (origin -> dest) for this day
        outbound_tasks = []
        for scraper in scrapers:
            reachable = set(airline_dests.get(scraper.airline_name, []))
            for dest in all_destinations:
                if dest in reachable:
                    outbound_tasks.append(
                        _fetch_flights_for_day(scraper, origin, dest, day)
                    )

        # Collect return flights (dest -> origin) for the same day
        return_tasks = []
        for scraper in scrapers:
            reachable = set(airline_dests.get(scraper.airline_name, []))
            for dest in all_destinations:
                if dest in reachable:
                    return_tasks.append(
                        _fetch_flights_for_day(scraper, dest, origin, day)
                    )

        # Run all tasks concurrently
        all_results = await asyncio.gather(
            *(outbound_tasks + return_tasks), return_exceptions=True
        )

        n_out = len(outbound_tasks)
        outbound_results = all_results[:n_out]
        return_results = all_results[n_out:]

        # Flatten and filter outbound flights (arrive before midday)
        outbound_by_dest: Dict[str, List[FlightResult]] = {}
        for res in outbound_results:
            if isinstance(res, Exception):
                continue
            for flight in res:
                if _qualifies_outbound(flight):
                    outbound_by_dest.setdefault(flight.destination, []).append(flight)

        # Flatten and filter return flights (depart after 16:00)
        return_by_dest: Dict[str, List[FlightResult]] = {}
        for res in return_results:
            if isinstance(res, Exception):
                continue
            for flight in res:
                if _qualifies_return(flight):
                    return_by_dest.setdefault(flight.origin, []).append(flight)

        # 3. Match: for each destination, pair cheapest outbound with cheapest return
        for dest in all_destinations:
            outs = outbound_by_dest.get(dest, [])
            rets = return_by_dest.get(dest, [])
            if not outs or not rets:
                continue
            # Generate all valid pairs and keep them all (sort globally later)
            for out_flight in outs:
                for ret_flight in rets:
                    results.append(DayTripResult(
                        outbound=out_flight,
                        return_flight=ret_flight,
                    ))

    # 4. Sort by total price
    results.sort(key=lambda r: r.total_price)
    return results


def format_day_trip(trip: DayTripResult, rank: int) -> str:
    """Format a single day trip result for display."""
    out = trip.outbound
    ret = trip.return_flight
    dep_time = out.departure_time.strftime("%H:%M") if out.departure_time else "?"
    arr_time = out.arrival_time.strftime("%H:%M") if out.arrival_time else "?"
    ret_dep = ret.departure_time.strftime("%H:%M") if ret.departure_time else "?"
    ret_arr = ret.arrival_time.strftime("%H:%M") if ret.arrival_time else "?"
    return (
        f"#{rank} {out.origin} -> {out.destination} "
        f"| {out.departure_date.strftime('%a %d %b')}\n"
        f"  OUT: {out.airline.title()} {dep_time}->{arr_time} "
        f"EUR {out.price_eur:.2f}\n"
        f"  RET: {ret.airline.title()} {ret_dep}->{ret_arr} "
        f"EUR {ret.price_eur:.2f}\n"
        f"  TOTAL: EUR {trip.total_price:.2f}"
    )


def format_day_trip_telegram(trip: DayTripResult, rank: int) -> str:
    """Format a day trip result as a Telegram Markdown message."""
    out = trip.outbound
    ret = trip.return_flight
    dep_time = out.departure_time.strftime("%H:%M") if out.departure_time else "?"
    arr_time = out.arrival_time.strftime("%H:%M") if out.arrival_time else "?"
    ret_dep = ret.departure_time.strftime("%H:%M") if ret.departure_time else "?"
    ret_arr = ret.arrival_time.strftime("%H:%M") if ret.arrival_time else "?"
    date_str = out.departure_date.strftime("%a %d %b")
    return (
        f"✈️ *#{rank} — {out.origin} → {out.destination}* | {date_str}\n"
        f"🛫 {out.airline.title()} {dep_time}→{arr_time} | €{out.price_eur:.2f}\n"
        f"🛬 {ret.airline.title()} {ret_dep}→{ret_arr} | €{ret.price_eur:.2f}\n"
        f"💰 *Total: €{trip.total_price:.2f}*"
    )
