import json
from datetime import datetime, timezone

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
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Job ID must be a number.")
        return
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
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Job ID must be a number.")
        return
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
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Job ID must be a number.")
        return
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
        f"Time: {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
        parse_mode="Markdown",
    )
