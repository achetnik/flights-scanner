import pytest
from datetime import date, datetime
from sqlmodel import Session, SQLModel, create_engine
from database import Job, SeenFlight, JobStatus, init_db, get_engine

@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(e)
    return e

def test_create_job(engine):
    with Session(engine) as session:
        job = Job(
            name="Test Trip",
            origin="TLV",
            destinations='["FCO"]',
            airlines='["ryanair"]',
            date_from=date(2025, 6, 1),
            date_to=date(2025, 8, 31),
            check_interval_minutes=30,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        assert job.status == JobStatus.ACTIVE
        assert job.passengers == 2
        assert job.bags_kg == 10

def test_create_seen_flight(engine):
    with Session(engine) as session:
        job = Job(
            origin="TLV",
            destinations='["FCO"]',
            airlines='["ryanair"]',
            date_from=date(2025, 6, 1),
            date_to=date(2025, 8, 31),
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        seen = SeenFlight(
            job_id=job.id,
            flight_fingerprint="abc123",
        )
        session.add(seen)
        session.commit()
        session.refresh(seen)
        assert seen.id is not None
        assert seen.last_alerted_at is not None

def test_job_status_enum(engine):
    with Session(engine) as session:
        job = Job(
            origin="TLV",
            destinations='["FCO"]',
            airlines='["ryanair"]',
            date_from=date(2025, 6, 1),
            date_to=date(2025, 8, 31),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job.status = JobStatus.PAUSED
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.status == JobStatus.PAUSED
