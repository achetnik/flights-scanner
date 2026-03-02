# Flight Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Telegram-managed flight monitoring system that scrapes airline websites (Ryanair, EasyJet, Wizzair) on a schedule, detects available flights to configured destinations, and sends Telegram notifications with direct booking links.

**Architecture:** Multiple independent search jobs (each with own origin, destinations, airlines, dates, interval) stored in SQLite, managed via Telegram bot commands. APScheduler runs each job independently. Playwright scrapes JS-rendered airline sites. FastAPI serves as the Telegram webhook endpoint deployed on Railway.

**Tech Stack:** Python 3.12, python-telegram-bot v21, Playwright (Chromium), APScheduler, SQLModel (SQLite), FastAPI, uvicorn, Railway

---

## Prerequisites

Before starting, have these ready:
- Telegram bot token: create via @BotFather on Telegram (`/newbot`)
- Your Telegram chat ID: message @userinfobot on Telegram
- Railway account: https://railway.app (free tier)
- Python 3.12 installed locally

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `railway.toml`
- Create: `.gitignore`
- Create: `scrapers/__init__.py`
- Create: `bot/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p scrapers bot tests
touch scrapers/__init__.py bot/__init__.py tests/__init__.py
```

**Step 2: Create `requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-telegram-bot==21.6
playwright==1.47.0
apscheduler==3.10.4
sqlmodel==0.0.21
python-dotenv==1.0.1
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

**Step 3: Create `.env.example`**

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
WEBHOOK_URL=https://your-app.railway.app
DATABASE_URL=sqlite:///./flights.db
```

**Step 4: Create `railway.toml`**

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "playwright install chromium && uvicorn main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

**Step 5: Create `.gitignore`**

```
.env
*.db
__pycache__/
.playwright/
*.pyc
.pytest_cache/
```

**Step 6: Install dependencies**

```bash
pip install -r requirements.txt
playwright install chromium
```

**Step 7: Commit**

```bash
git init
git add .
git commit -m "feat: initial project scaffolding"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
import pytest
from datetime import date
from models import JobConfig, FlightResult

def test_job_config_defaults():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO", "BCN"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 8, 31),
    )
    assert job.passengers == 2
    assert job.bags_kg == 10
    assert job.check_interval_minutes == 30

def test_flight_result_fingerprint():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_eur=89.0,
        booking_url="https://ryanair.com/...",
        flight_number="FR1234",
    )
    fp = flight.fingerprint
    assert isinstance(fp, str)
    assert len(fp) == 64  # SHA-256 hex

def test_flight_result_fingerprint_is_deterministic():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_eur=89.0,
        booking_url="https://ryanair.com/...",
        flight_number="FR1234",
    )
    assert flight.fingerprint == flight.fingerprint
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'models'`

**Step 3: Write `models.py`**

```python
import hashlib
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, field_validator


class JobConfig(BaseModel):
    name: Optional[str] = None
    origin: str
    destinations: List[str]
    airlines: List[str]
    date_from: date
    date_to: date
    passengers: int = 2
    bags_kg: int = 10
    check_interval_minutes: int = 30

    @field_validator("origin", "destinations", mode="before")
    @classmethod
    def uppercase_iata(cls, v):
        if isinstance(v, str):
            return v.upper()
        return [x.upper() for x in v]


class FlightResult(BaseModel):
    airline: str
    origin: str
    destination: str
    departure_date: date
    price_eur: float
    booking_url: str
    flight_number: str
    return_date: Optional[date] = None

    @property
    def fingerprint(self) -> str:
        key = f"{self.airline}:{self.flight_number}:{self.departure_date}:{self.origin}:{self.destination}"
        return hashlib.sha256(key.encode()).hexdigest()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add Job and Flight pydantic models"
```

---

### Task 3: Database Models

**Files:**
- Create: `database.py`
- Create: `tests/test_database.py`

**Step 1: Write the failing test**

```python
# tests/test_database.py
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
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_database.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'database'`

**Step 3: Write `database.py`**

```python
import os
from datetime import datetime
from enum import Enum
from typing import Optional
from datetime import date

from sqlmodel import Field, Session, SQLModel, create_engine


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_run_at: Optional[datetime] = None


class SeenFlight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    flight_fingerprint: str = Field(index=True)
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_alerted_at: datetime = Field(default_factory=datetime.utcnow)


def get_engine():
    database_url = os.getenv("DATABASE_URL", "sqlite:///./flights.db")
    return create_engine(database_url, connect_args={"check_same_thread": False})


def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    return engine
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_database.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: add SQLModel database models for jobs and seen flights"
```

---

### Task 4: Base Scraper Interface

**Files:**
- Create: `scrapers/base.py`
- Create: `tests/test_base_scraper.py`

**Step 1: Write the failing test**

```python
# tests/test_base_scraper.py
import pytest
from datetime import date
from unittest.mock import AsyncMock
from models import JobConfig, FlightResult
from scrapers.base import BaseScraper


class ConcreteTestScraper(BaseScraper):
    airline_name = "test"

    async def search(self, origin: str, destination: str, job: JobConfig) -> list[FlightResult]:
        return [
            FlightResult(
                airline="test",
                origin=origin,
                destination=destination,
                departure_date=date(2025, 6, 14),
                price_eur=99.0,
                booking_url="https://test.com",
                flight_number="T001",
            )
        ]


@pytest.mark.asyncio
async def test_scraper_returns_flights():
    scraper = ConcreteTestScraper()
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["test"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 8, 31),
    )
    flights = await scraper.search("TLV", "FCO", job)
    assert len(flights) == 1
    assert flights[0].airline == "test"
    assert flights[0].origin == "TLV"
    assert flights[0].destination == "FCO"


def test_base_scraper_cannot_be_instantiated_without_airline_name():
    class BadScraper(BaseScraper):
        async def search(self, origin, destination, job):
            return []

    # Missing airline_name — should raise
    with pytest.raises(TypeError):
        BadScraper()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_base_scraper.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`

**Step 3: Write `scrapers/base.py`**

```python
from abc import ABC, abstractmethod
from typing import List
from models import JobConfig, FlightResult


class BaseScraper(ABC):
    airline_name: str  # subclasses MUST define this

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "airline_name"):
            raise TypeError(f"{cls.__name__} must define 'airline_name'")

    @abstractmethod
    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        """Search for flights. Return list of found flights (may be empty)."""
        ...
```

**Step 4: Add `pytest-asyncio` config to `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_base_scraper.py -v
```
Expected: `2 passed`

**Step 6: Commit**

```bash
git add scrapers/base.py tests/test_base_scraper.py pytest.ini
git commit -m "feat: add base scraper abstract interface"
```

---

### Task 5: Ryanair Scraper

**Files:**
- Create: `scrapers/ryanair.py`
- Create: `tests/test_ryanair_scraper.py`

**Context:** Ryanair exposes an internal availability API at `/api/booking/v4/availability`. We call this with `httpx` (faster and more reliable than Playwright for JSON APIs). We use Playwright only if the API requires browser headers.

**Step 1: Write the failing test**

```python
# tests/test_ryanair_scraper.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.ryanair import RyanairScraper


MOCK_API_RESPONSE = {
    "trips": [
        {
            "origin": "TLV",
            "destination": "FCO",
            "dates": [
                {
                    "dateOut": "2025-06-14T00:00:00.000",
                    "flights": [
                        {
                            "flightNumber": "FR1234",
                            "regularFare": {
                                "fares": [{"amount": 89.99}]
                            },
                            "time": ["2025-06-14T06:00:00.000", "2025-06-14T09:00:00.000"],
                        }
                    ],
                }
            ],
        }
    ]
}


@pytest.mark.asyncio
async def test_ryanair_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_API_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "ryanair"
    assert flights[0].flight_number == "FR1234"
    assert flights[0].price_eur == 89.99
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "ryanair.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_ryanair_returns_empty_on_no_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["ryanair"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    empty_response = {"trips": [{"origin": "TLV", "destination": "FCO", "dates": []}]}

    with patch("scrapers.ryanair.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = RyanairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert flights == []
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_ryanair_scraper.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'scrapers.ryanair'`

**Step 3: Write `scrapers/ryanair.py`**

```python
import httpx
from datetime import date, datetime
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
            # advance by 1 day (Ryanair API returns one day at a time)
            from datetime import timedelta
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
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_ryanair_scraper.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add scrapers/ryanair.py tests/test_ryanair_scraper.py
git commit -m "feat: add Ryanair scraper using availability API"
```

---

### Task 6: EasyJet Scraper

**Files:**
- Create: `scrapers/easyjet.py`
- Create: `tests/test_easyjet_scraper.py`

**Context:** EasyJet has an internal search API at `https://www.easyjet.com/api/routepricing/v2/search`. We extract price and flight data from JSON response.

**Step 1: Write the failing test**

```python
# tests/test_easyjet_scraper.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.easyjet import EasyJetScraper

MOCK_EJ_RESPONSE = {
    "outboundFlights": [
        {
            "id": "EJU1234",
            "departureDateTime": "2025-06-14T07:30:00",
            "arrivalDateTime": "2025-06-14T10:30:00",
            "priceInPennies": 8999,
            "currency": "GBP",
            "priceInEur": 10500,
        }
    ]
}


@pytest.mark.asyncio
async def test_easyjet_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["easyjet"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )

    with patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_EJ_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = EasyJetScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "easyjet"
    assert flights[0].flight_number == "EJU1234"
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "easyjet.com" in flights[0].booking_url


@pytest.mark.asyncio
async def test_easyjet_empty_on_no_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["easyjet"],
        date_from=date(2025, 6, 14),
        date_to=date(2025, 6, 14),
    )
    empty_response = {"outboundFlights": []}

    with patch("scrapers.easyjet.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = EasyJetScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert flights == []
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_easyjet_scraper.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`

**Step 3: Write `scrapers/easyjet.py`**

```python
import httpx
from datetime import date, datetime, timedelta
from typing import List

from models import JobConfig, FlightResult
from scrapers.base import BaseScraper

EASYJET_API_URL = "https://www.easyjet.com/api/routepricing/v2/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


class EasyJetScraper(BaseScraper):
    airline_name = "easyjet"

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
        dep_date: date,
        job: JobConfig,
    ) -> List[FlightResult]:
        params = {
            "originIata": origin,
            "destinationIata": destination,
            "departureDate": dep_date.strftime("%Y-%m-%d"),
            "adults": job.passengers,
            "children": 0,
            "infants": 0,
        }
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.get(EASYJET_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        return self._parse_response(data, origin, destination)

    def _parse_response(self, data: dict, origin: str, destination: str) -> List[FlightResult]:
        results = []
        for flight in data.get("outboundFlights", []):
            dep_str = flight.get("departureDateTime", "")[:10]
            if not dep_str:
                continue
            dep_date = datetime.strptime(dep_str, "%Y-%m-%d").date()
            price_eur = flight.get("priceInEur", 0) / 100
            if price_eur <= 0:
                continue
            flight_id = flight.get("id", "")
            booking_url = self._build_booking_url(origin, destination, dep_date)
            results.append(FlightResult(
                airline="easyjet",
                origin=origin,
                destination=destination,
                departure_date=dep_date,
                price_eur=price_eur,
                booking_url=booking_url,
                flight_number=flight_id,
            ))
        return results

    def _build_booking_url(self, origin: str, destination: str, dep_date: date) -> str:
        d = dep_date.strftime("%Y-%m-%d")
        return (
            f"https://www.easyjet.com/en/cheap-flights/{origin.lower()}/{destination.lower()}"
            f"?departDate={d}&adults=2"
        )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_easyjet_scraper.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add scrapers/easyjet.py tests/test_easyjet_scraper.py
git commit -m "feat: add EasyJet scraper"
```

---

### Task 7: Wizzair Scraper

**Files:**
- Create: `scrapers/wizzair.py`
- Create: `tests/test_wizzair_scraper.py`

**Context:** Wizzair exposes a timetable API at `https://be.wizzair.com/24.2.0/Api/search/timetable`. Requires `wdc` session cookie obtained from homepage. We use Playwright to get the cookie, then make the API call with httpx.

**Step 1: Write the failing test**

```python
# tests/test_wizzair_scraper.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from models import JobConfig, FlightResult
from scrapers.wizzair import WizzairScraper

MOCK_WIZZAIR_RESPONSE = {
    "outboundFlights": [
        {
            "departureStation": "TLV",
            "arrivalStation": "FCO",
            "departureDates": ["2025-06-14T06:00:00"],
            "price": {"amount": 75.0, "currencyCode": "EUR"},
            "flightNumbers": ["W62345"],
        }
    ]
}


@pytest.mark.asyncio
async def test_wizzair_parses_flights():
    job = JobConfig(
        origin="TLV",
        destinations=["FCO"],
        airlines=["wizzair"],
        date_from=date(2025, 6, 1),
        date_to=date(2025, 6, 30),
    )

    with patch.object(WizzairScraper, "_get_session_cookie", new_callable=AsyncMock) as mock_cookie, \
         patch("scrapers.wizzair.httpx.AsyncClient") as mock_client_cls:

        mock_cookie.return_value = "mock_wdc_cookie"
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_WIZZAIR_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        scraper = WizzairScraper()
        flights = await scraper.search("TLV", "FCO", job)

    assert len(flights) == 1
    assert flights[0].airline == "wizzair"
    assert flights[0].price_eur == 75.0
    assert flights[0].departure_date == date(2025, 6, 14)
    assert "wizzair.com" in flights[0].booking_url
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_wizzair_scraper.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`

**Step 3: Write `scrapers/wizzair.py`**

```python
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
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_wizzair_scraper.py -v
```
Expected: `1 passed`

**Step 5: Commit**

```bash
git add scrapers/wizzair.py tests/test_wizzair_scraper.py
git commit -m "feat: add Wizzair scraper with Playwright session cookie"
```

---

### Task 8: Scraper Registry

**Files:**
- Create: `scrapers/registry.py`
- Create: `tests/test_scraper_registry.py`

**Step 1: Write the failing test**

```python
# tests/test_scraper_registry.py
import pytest
from scrapers.registry import get_scraper, list_scrapers
from scrapers.ryanair import RyanairScraper
from scrapers.easyjet import EasyJetScraper
from scrapers.wizzair import WizzairScraper


def test_get_scraper_ryanair():
    scraper = get_scraper("ryanair")
    assert isinstance(scraper, RyanairScraper)


def test_get_scraper_easyjet():
    scraper = get_scraper("easyjet")
    assert isinstance(scraper, EasyJetScraper)


def test_get_scraper_wizzair():
    scraper = get_scraper("wizzair")
    assert isinstance(scraper, WizzairScraper)


def test_get_scraper_unknown_raises():
    with pytest.raises(ValueError, match="Unknown airline"):
        get_scraper("unknownair")


def test_list_scrapers():
    names = list_scrapers()
    assert "ryanair" in names
    assert "easyjet" in names
    assert "wizzair" in names
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_scraper_registry.py -v
```

**Step 3: Write `scrapers/registry.py`**

```python
from typing import List
from scrapers.base import BaseScraper
from scrapers.ryanair import RyanairScraper
from scrapers.easyjet import EasyJetScraper
from scrapers.wizzair import WizzairScraper

_REGISTRY = {
    "ryanair": RyanairScraper,
    "easyjet": EasyJetScraper,
    "wizzair": WizzairScraper,
}


def get_scraper(airline: str) -> BaseScraper:
    cls = _REGISTRY.get(airline.lower())
    if not cls:
        raise ValueError(f"Unknown airline: {airline}. Available: {list(_REGISTRY.keys())}")
    return cls()


def list_scrapers() -> List[str]:
    return list(_REGISTRY.keys())
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_scraper_registry.py -v
```
Expected: `5 passed`

**Step 5: Commit**

```bash
git add scrapers/registry.py tests/test_scraper_registry.py
git commit -m "feat: add scraper registry for airline lookup"
```

---

### Task 9: Telegram Notifier

**Files:**
- Create: `notifier.py`
- Create: `tests/test_notifier.py`

**Step 1: Write the failing test**

```python
# tests/test_notifier.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from models import FlightResult
from notifier import format_flight_message, send_flight_alert


def test_format_flight_message():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_eur=89.99,
        booking_url="https://ryanair.com/book",
        flight_number="FR1234",
    )
    msg = format_flight_message(flight, job_name="Summer Europe", job_id=3)
    assert "FR1234" in msg
    assert "TLV" in msg
    assert "FCO" in msg
    assert "89.99" in msg
    assert "https://ryanair.com/book" in msg
    assert "Summer Europe" in msg or "#3" in msg


@pytest.mark.asyncio
async def test_send_flight_alert_calls_telegram():
    flight = FlightResult(
        airline="ryanair",
        origin="TLV",
        destination="FCO",
        departure_date=date(2025, 6, 14),
        price_eur=89.99,
        booking_url="https://ryanair.com/book",
        flight_number="FR1234",
    )

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()

    await send_flight_alert(mock_bot, chat_id="123", flight=flight, job_name="Test", job_id=1)
    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "123"
    assert "FR1234" in call_kwargs["text"]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_notifier.py -v
```

**Step 3: Write `notifier.py`**

```python
from models import FlightResult
from telegram import Bot
from telegram.constants import ParseMode


def format_flight_message(flight: FlightResult, job_name: str, job_id: int) -> str:
    label = f"{job_name} #{job_id}" if job_name else f"Job #{job_id}"
    dep = flight.departure_date.strftime("%b %d, %Y")
    return (
        f"🚀 *New flight found!* [{label}]\n"
        f"{flight.origin} → {flight.destination} | {flight.airline.title()} {flight.flight_number}\n"
        f"📅 {dep}\n"
        f"💰 €{flight.price_eur:.2f}/person — 2 adults, 10kg bags\n"
        f"[Book now →]({flight.booking_url})"
    )


async def send_flight_alert(
    bot: Bot,
    chat_id: str,
    flight: FlightResult,
    job_name: str,
    job_id: int,
) -> None:
    text = format_flight_message(flight, job_name, job_id)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_notifier.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier with flight message formatting"
```

---

### Task 10: Job Runner

**Files:**
- Create: `job_runner.py`
- Create: `tests/test_job_runner.py`

**Context:** The job runner takes a Job from DB, runs all configured scrapers, deduplicates against `seen_flights`, and triggers notifications for new flights.

**Step 1: Write the failing test**

```python
# tests/test_job_runner.py
import pytest
import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session, SQLModel, create_engine
from database import Job, SeenFlight, init_db
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
            last_alerted_at=datetime.utcnow() - timedelta(hours=25),
        )
        session.add(seen)
        session.commit()
        assert is_new_flight(session, sample_job.id, flight) is True
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_job_runner.py -v
```

**Step 3: Write `job_runner.py`**

```python
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from database import Job, SeenFlight, get_engine
from models import FlightResult, JobConfig
from notifier import send_flight_alert
from scrapers.registry import get_scraper

logger = logging.getLogger(__name__)

DEDUP_HOURS = 24


def is_new_flight(session: Session, job_id: int, flight: FlightResult) -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_HOURS)
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
        existing.last_alerted_at = datetime.utcnow()
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
            db_job.last_run_at = datetime.utcnow()
            session.add(db_job)
            session.commit()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_job_runner.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add job_runner.py tests/test_job_runner.py
git commit -m "feat: add job runner with deduplication logic"
```

---

### Task 11: Telegram Bot — /newjob Wizard

**Files:**
- Create: `bot/wizard.py`
- Create: `tests/test_bot_wizard.py`

**Context:** Uses `ConversationHandler` from python-telegram-bot. The wizard asks questions step by step and builds a Job record at the end.

**Step 1: Write the failing test**

```python
# tests/test_bot_wizard.py
import pytest
from bot.wizard import parse_airlines, parse_iata_list, parse_date_range
from datetime import date


def test_parse_iata_list():
    assert parse_iata_list("TLV FCO BCN") == ["TLV", "FCO", "BCN"]
    assert parse_iata_list("tlv, fco") == ["TLV", "FCO"]
    assert parse_iata_list("FCO") == ["FCO"]


def test_parse_airlines_all():
    assert set(parse_airlines("4")) == {"ryanair", "easyjet", "wizzair"}
    assert set(parse_airlines("all")) == {"ryanair", "easyjet", "wizzair"}


def test_parse_airlines_single():
    result = parse_airlines("1")
    assert result == ["ryanair"]


def test_parse_airlines_multiple():
    result = parse_airlines("1 2")
    assert set(result) == {"ryanair", "easyjet"}


def test_parse_date_range_iso():
    start, end = parse_date_range("2025-06-01 to 2025-08-31")
    assert start == date(2025, 6, 1)
    assert end == date(2025, 8, 31)


def test_parse_date_range_natural():
    start, end = parse_date_range("June to August 2025")
    assert start == date(2025, 6, 1)
    assert end == date(2025, 8, 31)


def test_parse_date_range_invalid_raises():
    with pytest.raises(ValueError):
        parse_date_range("not a date")
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_bot_wizard.py -v
```

**Step 3: Write `bot/wizard.py`**

```python
import re
from datetime import date
from typing import List, Tuple

AIRLINE_OPTIONS = {
    "1": "ryanair",
    "2": "easyjet",
    "3": "wizzair",
}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Conversation states
(
    ASK_ORIGIN,
    ASK_DESTINATIONS,
    ASK_AIRLINES,
    ASK_DATE_RANGE,
    ASK_INTERVAL,
    ASK_NAME,
    CONFIRM,
) = range(7)


def parse_iata_list(text: str) -> List[str]:
    codes = re.split(r"[\s,]+", text.strip())
    return [c.upper() for c in codes if c]


def parse_airlines(text: str) -> List[str]:
    text = text.strip().lower()
    if text in ("4", "all"):
        return list(AIRLINE_OPTIONS.values())
    codes = re.split(r"[\s,]+", text)
    result = []
    for c in codes:
        if c in AIRLINE_OPTIONS:
            result.append(AIRLINE_OPTIONS[c])
        elif c in AIRLINE_OPTIONS.values():
            result.append(c)
    return list(set(result)) if result else list(AIRLINE_OPTIONS.values())


def parse_date_range(text: str) -> Tuple[date, date]:
    # Try ISO: "2025-06-01 to 2025-08-31"
    iso_match = re.search(
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE
    )
    if iso_match:
        start = date.fromisoformat(iso_match.group(1))
        end = date.fromisoformat(iso_match.group(2))
        return start, end

    # Try natural: "June to August 2025"
    natural_match = re.search(
        r"([a-z]+)\s+to\s+([a-z]+)\s+(\d{4})", text, re.IGNORECASE
    )
    if natural_match:
        m1 = MONTH_MAP.get(natural_match.group(1).lower())
        m2 = MONTH_MAP.get(natural_match.group(2).lower())
        year = int(natural_match.group(3))
        if m1 and m2:
            start = date(year, m1, 1)
            # Last day of end month
            import calendar
            last_day = calendar.monthrange(year, m2)[1]
            end = date(year, m2, last_day)
            return start, end

    raise ValueError(f"Cannot parse date range: {text!r}. Use 'YYYY-MM-DD to YYYY-MM-DD' or 'Month to Month YYYY'")


async def newjob_start(update, context):
    await update.message.reply_text(
        "Let's create a new flight search job!\n\n"
        "What's your *origin airport*? (IATA code, e.g. TLV)",
        parse_mode="Markdown",
    )
    return ASK_ORIGIN


async def ask_destinations(update, context):
    context.user_data["origin"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "Destination(s)? Space or comma-separated IATA codes (e.g. `FCO BCN AMS`)",
        parse_mode="Markdown",
    )
    return ASK_DESTINATIONS


async def ask_airlines(update, context):
    context.user_data["destinations"] = parse_iata_list(update.message.text)
    await update.message.reply_text(
        "Which airlines to check?\n"
        "1. Ryanair\n2. EasyJet\n3. Wizzair\n4. All\n\n"
        "Reply with number(s), e.g. `1 2` or `4` for all",
        parse_mode="Markdown",
    )
    return ASK_AIRLINES


async def ask_date_range(update, context):
    context.user_data["airlines"] = parse_airlines(update.message.text)
    await update.message.reply_text(
        "Date range? (e.g. `2025-06-01 to 2025-08-31` or `June to August 2025`)",
        parse_mode="Markdown",
    )
    return ASK_DATE_RANGE


async def ask_interval(update, context):
    try:
        start, end = parse_date_range(update.message.text)
    except ValueError as e:
        await update.message.reply_text(f"Couldn't parse that date. {e}\nTry again:")
        return ASK_DATE_RANGE
    context.user_data["date_from"] = start
    context.user_data["date_to"] = end
    await update.message.reply_text(
        "Check every how many minutes? (default: 30, min: 15)",
        parse_mode="Markdown",
    )
    return ASK_INTERVAL


async def ask_name(update, context):
    text = update.message.text.strip()
    try:
        interval = max(15, int(text))
    except ValueError:
        interval = 30
    context.user_data["check_interval_minutes"] = interval
    await update.message.reply_text(
        "Job name? (optional — for your reference, e.g. 'Summer Rome')\n"
        "Or send /skip to use a default name.",
        parse_mode="Markdown",
    )
    return ASK_NAME


async def confirm_job(update, context):
    text = update.message.text.strip()
    if text.lower() != "/skip":
        context.user_data["name"] = text

    data = context.user_data
    name = data.get("name", f"{data['origin']}→{','.join(data['destinations'])}")
    msg = (
        f"Creating job: *{name}*\n"
        f"Route: {data['origin']} → {', '.join(data['destinations'])}\n"
        f"Airlines: {', '.join(data['airlines'])}\n"
        f"Dates: {data['date_from']} to {data['date_to']}\n"
        f"Interval: every {data['check_interval_minutes']} min\n"
        f"Passengers: 2 adults, 10kg bags"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return await _save_job(update, context)


async def _save_job(update, context):
    import json
    import os
    from sqlmodel import Session
    from database import Job, get_engine

    data = context.user_data
    name = data.get("name")
    engine = get_engine()
    with Session(engine) as session:
        job = Job(
            name=name,
            origin=data["origin"],
            destinations=json.dumps(data["destinations"]),
            airlines=json.dumps(data["airlines"]),
            date_from=data["date_from"],
            date_to=data["date_to"],
            check_interval_minutes=data["check_interval_minutes"],
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    # Register with scheduler
    from scheduler import add_job_to_scheduler
    add_job_to_scheduler(job_id, data["check_interval_minutes"])

    await update.message.reply_text(
        f"Job #{job_id} created and running!",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    from telegram.ext import ConversationHandler
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("Job creation cancelled.")
    from telegram.ext import ConversationHandler
    return ConversationHandler.END
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_bot_wizard.py -v
```
Expected: `7 passed`

**Step 5: Commit**

```bash
git add bot/wizard.py tests/test_bot_wizard.py
git commit -m "feat: add /newjob Telegram conversation wizard"
```

---

### Task 12: Telegram Bot — Management Commands

**Files:**
- Create: `bot/handlers.py`

**Step 1: Write `bot/handlers.py`** (no unit tests — these are thin Telegram adapter functions)

```python
import json
from datetime import datetime

from sqlmodel import Session, select
from telegram import Update
from telegram.ext import ContextTypes

from database import Job, JobStatus, get_engine


async def cmd_listjobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    engine = get_engine()
    with Session(engine) as session:
        jobs = session.exec(select(Job)).all()

    if not jobs:
        await update.message.reply_text("No jobs yet. Use /newjob to create one.")
        return

    lines = ["*Your search jobs:*\n"]
    for job in jobs:
        dests = ", ".join(json.loads(job.destinations))
        last = job.last_run_at.strftime("%H:%M %d/%m") if job.last_run_at else "never"
        lines.append(
            f"#{job.id} *{job.name or 'unnamed'}* [{job.status.value}]\n"
            f"  {job.origin} → {dests}\n"
            f"  Every {job.check_interval_minutes}min | Last: {last}"
        )
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_stopjob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /stopjob <job_id>")
        return
    job_id = int(context.args[0])
    engine = get_engine()
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            await update.message.reply_text(f"Job #{job_id} not found.")
            return
        job.status = JobStatus.STOPPED
        session.add(job)
        session.commit()

    from scheduler import remove_job_from_scheduler
    remove_job_from_scheduler(job_id)
    await update.message.reply_text(f"Job #{job_id} stopped.")


async def cmd_pausejob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /pausejob <job_id>")
        return
    job_id = int(context.args[0])
    engine = get_engine()
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            await update.message.reply_text(f"Job #{job_id} not found.")
            return
        job.status = JobStatus.PAUSED
        session.add(job)
        session.commit()

    from scheduler import pause_job_in_scheduler
    pause_job_in_scheduler(job_id)
    await update.message.reply_text(f"Job #{job_id} paused.")


async def cmd_resumejob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /resumejob <job_id>")
        return
    job_id = int(context.args[0])
    engine = get_engine()
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            await update.message.reply_text(f"Job #{job_id} not found.")
            return
        job.status = JobStatus.ACTIVE
        session.add(job)
        session.commit()

    from scheduler import resume_job_in_scheduler
    resume_job_in_scheduler(job_id)
    await update.message.reply_text(f"Job #{job_id} resumed.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    engine = get_engine()
    with Session(engine) as session:
        jobs = session.exec(select(Job)).all()

    active = sum(1 for j in jobs if j.status == JobStatus.ACTIVE)
    paused = sum(1 for j in jobs if j.status == JobStatus.PAUSED)
    await update.message.reply_text(
        f"*System Status*\n"
        f"Active jobs: {active}\n"
        f"Paused jobs: {paused}\n"
        f"Total jobs: {len(jobs)}\n"
        f"Time: {datetime.utcnow().strftime('%H:%M UTC')}",
        parse_mode="Markdown",
    )
```

**Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: add Telegram bot management command handlers"
```

---

### Task 13: APScheduler Job Manager

**Files:**
- Create: `scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
# tests/test_scheduler.py
import pytest
from unittest.mock import MagicMock, patch
from scheduler import FlightScheduler


def test_scheduler_starts():
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()
    assert sched.scheduler.running
    sched.scheduler.shutdown()


def test_add_job(monkeypatch):
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()

    with patch("scheduler.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        sched.add_job(job_id=1, interval_minutes=30)
        job = sched.scheduler.get_job(f"flight_job_{1}")
        assert job is not None

    sched.scheduler.shutdown()


def test_remove_job():
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()
    sched.add_job(job_id=99, interval_minutes=30)
    sched.remove_job(job_id=99)
    job = sched.scheduler.get_job("flight_job_99")
    assert job is None
    sched.scheduler.shutdown()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_scheduler.py -v
```

**Step 3: Write `scheduler.py`**

```python
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, select

from database import Job, JobStatus, get_engine
from job_runner import run_job

logger = logging.getLogger(__name__)

# Module-level singleton (set by main.py)
_scheduler_instance = None


def get_scheduler() -> "FlightScheduler":
    return _scheduler_instance


def add_job_to_scheduler(job_id: int, interval_minutes: int):
    if _scheduler_instance:
        _scheduler_instance.add_job(job_id, interval_minutes)


def remove_job_from_scheduler(job_id: int):
    if _scheduler_instance:
        _scheduler_instance.remove_job(job_id)


def pause_job_in_scheduler(job_id: int):
    if _scheduler_instance:
        _scheduler_instance.scheduler.pause_job(f"flight_job_{job_id}")


def resume_job_in_scheduler(job_id: int):
    if _scheduler_instance:
        _scheduler_instance.scheduler.resume_job(f"flight_job_{job_id}")


class FlightScheduler:
    def __init__(self, bot, chat_id: str):
        self.bot = bot
        self.chat_id = chat_id
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()
        global _scheduler_instance
        _scheduler_instance = self

    def add_job(self, job_id: int, interval_minutes: int):
        job_key = f"flight_job_{job_id}"
        if self.scheduler.get_job(job_key):
            self.scheduler.reschedule_job(
                job_key, trigger="interval", minutes=interval_minutes
            )
        else:
            self.scheduler.add_job(
                self._make_job_func(job_id),
                trigger="interval",
                minutes=interval_minutes,
                id=job_key,
                replace_existing=True,
                max_instances=1,
            )

    def remove_job(self, job_id: int):
        job_key = f"flight_job_{job_id}"
        if self.scheduler.get_job(job_key):
            self.scheduler.remove_job(job_key)

    def load_active_jobs(self):
        engine = get_engine()
        with Session(engine) as session:
            jobs = session.exec(
                select(Job).where(Job.status == JobStatus.ACTIVE)
            ).all()
        for job in jobs:
            self.add_job(job.id, job.check_interval_minutes)
        logger.info(f"Loaded {len(jobs)} active jobs from DB")

    def _make_job_func(self, job_id: int):
        bot = self.bot
        chat_id = self.chat_id

        async def run():
            engine = get_engine()
            with Session(engine) as session:
                job = session.get(Job, job_id)
                if not job or job.status != JobStatus.ACTIVE:
                    return
            await run_job(job, bot, chat_id)

        return run
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_scheduler.py -v
```
Expected: `3 passed`

**Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: add APScheduler-based job manager"
```

---

### Task 14: FastAPI App + Telegram Webhook

**Files:**
- Create: `main.py`

**Step 1: Write `main.py`**

```python
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import init_db
from scheduler import FlightScheduler
from bot.handlers import (
    cmd_listjobs,
    cmd_pausejob,
    cmd_resumejob,
    cmd_status,
    cmd_stopjob,
)
from bot.wizard import (
    ASK_AIRLINES,
    ASK_DATE_RANGE,
    ASK_DESTINATIONS,
    ASK_INTERVAL,
    ASK_NAME,
    ASK_ORIGIN,
    ask_airlines,
    ask_date_range,
    ask_destinations,
    ask_interval,
    ask_name,
    cancel,
    confirm_job,
    newjob_start,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# Build Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# /newjob conversation
newjob_handler = ConversationHandler(
    entry_points=[CommandHandler("newjob", newjob_start)],
    states={
        ASK_ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_destinations)],
        ASK_DESTINATIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_airlines)],
        ASK_AIRLINES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date_range)],
        ASK_DATE_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_interval)],
        ASK_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
        ASK_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_job),
            CommandHandler("skip", confirm_job),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

application.add_handler(newjob_handler)
application.add_handler(CommandHandler("listjobs", cmd_listjobs))
application.add_handler(CommandHandler("stopjob", cmd_stopjob))
application.add_handler(CommandHandler("pausejob", cmd_pausejob))
application.add_handler(CommandHandler("resumejob", cmd_resumejob))
application.add_handler(CommandHandler("status", cmd_status))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    await application.initialize()
    await application.bot.set_webhook(f"{WEBHOOK_URL}/webhook")

    flight_scheduler = FlightScheduler(bot=application.bot, chat_id=CHAT_ID)
    flight_scheduler.start()
    flight_scheduler.load_active_jobs()
    logger.info("Flight scanner started.")
    yield
    # Shutdown
    flight_scheduler.scheduler.shutdown()
    await application.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return Response(status_code=200)
```

**Step 2: Test the app starts locally**

```bash
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# Set WEBHOOK_URL=https://localhost (temporary, update after Railway deploy)
uvicorn main:app --reload --port 8000
```

Expected: App starts, no import errors, `/health` returns `{"status": "ok"}`

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add FastAPI app with Telegram webhook and scheduler startup"
```

---

### Task 15: Railway Deployment

**Files:**
- Modify: `.env` (set on Railway, not committed)
- Verify: `railway.toml`

**Step 1: Install Railway CLI**

```bash
brew install railway
railway login
```

**Step 2: Create Railway project**

```bash
railway init
railway add --name flights-scanner
```

**Step 3: Set environment variables on Railway**

```bash
railway variables set TELEGRAM_BOT_TOKEN=<your_token>
railway variables set TELEGRAM_CHAT_ID=<your_chat_id>
railway variables set DATABASE_URL=sqlite:///./flights.db
# WEBHOOK_URL will be set after first deploy — see next step
```

**Step 4: Deploy to get the public URL**

```bash
railway up
```

Expected: Railway assigns a URL like `https://flights-scanner-production.up.railway.app`

**Step 5: Set WEBHOOK_URL and redeploy**

```bash
railway variables set WEBHOOK_URL=https://flights-scanner-production.up.railway.app
railway up
```

**Step 6: Verify deployment**

```bash
curl https://flights-scanner-production.up.railway.app/health
```
Expected: `{"status":"ok"}`

**Step 7: Test bot in Telegram**

Open Telegram, find your bot, send:
```
/status
```
Expected: Bot replies with system status message.

**Step 8: Add persistent storage volume on Railway**

In Railway dashboard → your service → `+ Add Volume` → mount at `/app` → this ensures `flights.db` survives redeploys.

**Step 9: Commit final state**

```bash
git add railway.toml .env.example
git commit -m "feat: Railway deployment configuration"
```

---

### Task 16: End-to-End Smoke Test

**Step 1: Create a test job via Telegram**

Send to your bot:
```
/newjob
```
Follow the wizard:
- Origin: `TLV`
- Destinations: `FCO`
- Airlines: `4` (all)
- Dates: `2025-06-01 to 2025-06-30`
- Interval: `1` (1 minute for testing)
- Name: `smoke test`

**Step 2: Wait 1-2 minutes**

Watch for a flight alert notification OR check logs:
```bash
railway logs --tail
```

**Step 3: Verify deduplication**

After the first alert, wait another minute. The same flight should NOT trigger a second alert within 24h.

**Step 4: Test pause/resume**

```
/pausejob 1
/listjobs        ← should show status: paused
/resumejob 1
/listjobs        ← should show status: active
```

**Step 5: Change test interval back to 30 min**

Stop the smoke-test job and create a real one:
```
/stopjob 1
/newjob
```

---

## Run All Tests

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass. Any failures indicate which component needs attention before deploying.
