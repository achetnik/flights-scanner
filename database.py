import os
from datetime import datetime, date, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine


def _utcnow():
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = None
    status: JobStatus = JobStatus.ACTIVE
    origin: str
    destinations: str  # JSON list, e.g. '["FCO","BCN"]'
    airlines: str      # JSON list, e.g. '["ryanair","easyjet"]'
    date_from: date
    date_to: date
    passengers: int = 2
    bags_kg: int = 10
    check_interval_minutes: int = 30
    created_at: datetime = Field(default_factory=_utcnow)
    last_run_at: Optional[datetime] = None


class SeenFlight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    flight_fingerprint: str = Field(index=True)
    first_seen_at: datetime = Field(default_factory=_utcnow)
    last_alerted_at: datetime = Field(default_factory=_utcnow)


def get_engine():
    database_url = os.getenv("DATABASE_URL", "sqlite:///./flights.db")
    kwargs = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    return engine
