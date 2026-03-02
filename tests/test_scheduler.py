# tests/test_scheduler.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from scheduler import FlightScheduler


def test_scheduler_starts():
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()
    assert sched.scheduler.running
    sched.scheduler.shutdown(wait=False)


def test_add_job():
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()
    sched.add_job(job_id=1, interval_minutes=30)
    job = sched.scheduler.get_job("flight_job_1")
    assert job is not None
    sched.scheduler.shutdown(wait=False)


def test_remove_job():
    sched = FlightScheduler(bot=MagicMock(), chat_id="123")
    sched.start()
    sched.add_job(job_id=99, interval_minutes=30)
    sched.remove_job(job_id=99)
    job = sched.scheduler.get_job("flight_job_99")
    assert job is None
    sched.scheduler.shutdown(wait=False)
