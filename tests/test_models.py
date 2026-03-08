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
        price_gbp=89.0,
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
        price_gbp=89.0,
        booking_url="https://ryanair.com/...",
        flight_number="FR1234",
    )
    assert flight.fingerprint == flight.fingerprint
