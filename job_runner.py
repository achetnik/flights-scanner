import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from database import Job, SeenFlight, get_engine, JobStatus
from models import FlightResult, JobConfig
from notifier import send_flight_alert
from scrapers.registry import get_scraper

logger = logging.getLogger(__name__)

DEDUP_HOURS = 24


def is_new_flight(session: Session, job_id: int, flight: FlightResult) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)
    statement = select(SeenFlight).where(
        SeenFlight.job_id == job_id,
        SeenFlight.flight_fingerprint == flight.fingerprint,
        SeenFlight.last_alerted_at >= cutoff,
    )
    return session.exec(statement).first() is None


def mark_flight_seen(session: Session, job_id: int, flight: FlightResult) -> None:
    statement = select(SeenFlight).where(
        SeenFlight.job_id == job_id,
        SeenFlight.flight_fingerprint == flight.fingerprint,
    )
    existing = session.exec(statement).first()
    if existing:
        existing.last_alerted_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        seen = SeenFlight(job_id=job_id, flight_fingerprint=flight.fingerprint)
        session.add(seen)
    session.commit()


async def run_job(job: Job, bot, chat_id: str) -> None:
    engine = get_engine()
    airlines = json.loads(job.airlines)
    destinations = json.loads(job.destinations)

    job_config = JobConfig(
        name=job.name,
        origin=job.origin,
        destinations=destinations,
        airlines=airlines,
        date_from=job.date_from,
        date_to=job.date_to,
        passengers=job.passengers,
        bags_kg=job.bags_kg,
        check_interval_minutes=job.check_interval_minutes,
    )

    for airline in airlines:
        try:
            scraper = get_scraper(airline)
        except ValueError:
            logger.warning(f"Unknown airline {airline} in job {job.id}")
            continue

        for destination in destinations:
            try:
                flights = await scraper.search(job.origin, destination, job_config)
            except Exception as e:
                logger.error(f"Scraper {airline} failed for {job.origin}->{destination}: {e}")
                continue

            with Session(engine) as session:
                for flight in flights:
                    if is_new_flight(session, job.id, flight):
                        try:
                            await send_flight_alert(
                                bot=bot,
                                chat_id=chat_id,
                                flight=flight,
                                job_name=job.name or "",
                                job_id=job.id,
                            )
                            mark_flight_seen(session, job.id, flight)
                        except Exception as e:
                            logger.error(f"Failed to send alert: {e}")

    with Session(engine) as session:
        db_job = session.get(Job, job.id)
        if db_job:
            db_job.last_run_at = datetime.now(timezone.utc)
            session.add(db_job)
            session.commit()
