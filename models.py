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
