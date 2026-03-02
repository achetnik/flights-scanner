import json
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session, SQLModel, create_engine
from database import Job, SeenFlight, JobStatus
from models import FlightResult
from job_runner import run_job, is_new_flight, mark_flight_seen


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(e)
    return e


@pytest.fixture
def sample_job(engine):
    with Session(engine) as session:
        job = Job(
            name="Test",
            origin="TLV",
            destinations=json.dumps(["FCO"]),
            airlines=json.dumps(["ryanair"]),
            date_from=date(2025, 6, 1),
            date_to=date(2025, 6, 30),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def test_is_new_flight_returns_true_for_unseen(engine, sample_job):
    flight = FlightResult(
        airline="ryanair", origin="TLV", destination="FCO",
        departure_date=date(2025, 6, 14), price_eur=89.0,
        booking_url="https://ryanair.com", flight_number="FR1234",
    )
    with Session(engine) as session:
        assert is_new_flight(session, sample_job.id, flight) is True


def test_is_new_flight_returns_false_for_recently_seen(engine, sample_job):
    flight = FlightResult(
        airline="ryanair", origin="TLV", destination="FCO",
        departure_date=date(2025, 6, 14), price_eur=89.0,
        booking_url="https://ryanair.com", flight_number="FR1234",
    )
    with Session(engine) as session:
        mark_flight_seen(session, sample_job.id, flight)
        assert is_new_flight(session, sample_job.id, flight) is False


def test_is_new_flight_returns_true_after_24h(engine, sample_job):
    flight = FlightResult(
        airline="ryanair", origin="TLV", destination="FCO",
        departure_date=date(2025, 6, 14), price_eur=89.0,
        booking_url="https://ryanair.com", flight_number="FR1234",
    )
    with Session(engine) as session:
        seen = SeenFlight(
            job_id=sample_job.id,
            flight_fingerprint=flight.fingerprint,
            last_alerted_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        session.add(seen)
        session.commit()
        assert is_new_flight(session, sample_job.id, flight) is True
