import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, select

from database import Job, JobStatus, get_engine
from job_runner import run_job

logger = logging.getLogger(__name__)

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
