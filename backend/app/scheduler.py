"""APScheduler 3.x inside the app: AsyncIOScheduler with jobs persisted in Postgres.

Rules this follows (from the APScheduler docs): every job has a stable id and replace_existing=True, so a restart never
duplicates jobs; one scheduler process only; coalesce=True so a stretch of missed runs becomes one run.
Because the PC may sleep, each job is state-driven, and on startup any job overdue by its interval runs once ("catch-up").
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.db import pg
from app.jobs import runner, tasks  # noqa: F401  (importing tasks registers the jobs)

log = logging.getLogger("scheduler")
_scheduler: AsyncIOScheduler | None = None
_catchup_tasks: set[asyncio.Task] = set()


def _sqlalchemy_url() -> str:
    return settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def _trigger(minutes: int) -> IntervalTrigger:
    return IntervalTrigger(minutes=max(int(minutes), 1), timezone=ZoneInfo(settings.timezone))


def _apply(job_id: str, cfg: dict) -> None:
    """Create or update the scheduler entry for a job from its settings row."""
    assert _scheduler is not None
    _scheduler.add_job("app.jobs.runner:scheduled_run", trigger=_trigger(cfg["interval_minutes"]), args=[job_id],
                       id=job_id, name=runner.JOBS[job_id].title, replace_existing=True)
    if not cfg["enabled"]:
        _scheduler.pause_job(job_id)


def reschedule(job_id: str) -> None:
    """Call after the job's settings change in the UI."""
    if _scheduler is None:
        return
    _apply(job_id, runner.get_setting(job_id))


def next_run_time(job_id: str) -> datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(job_id)
    return getattr(job, "next_run_time", None) if job else None


def _overdue(job_id: str, cfg: dict) -> bool:
    last = pg.fetch_one("SELECT max(finished_at) AS t FROM job_runs WHERE job_id = %s AND status = 'ok'", (job_id,))
    t = last["t"] if last else None
    if t is None:
        return True
    return datetime.now(t.tzinfo) - t > timedelta(minutes=cfg["interval_minutes"])


async def _catch_up(job_id: str) -> None:
    await asyncio.sleep(3)             # let the app finish starting
    await runner.run_job(job_id, "catch-up")


async def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    runner.ensure_job_settings()
    closed = runner.close_interrupted_runs()
    if closed:
        log.info("closed %s run(s) interrupted by the last shutdown", closed)

    _scheduler = AsyncIOScheduler(
        timezone=ZoneInfo(settings.timezone),
        jobstores={"default": SQLAlchemyJobStore(url=_sqlalchemy_url(), tablename="apscheduler_jobs")},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 6 * 3600},
    )
    _scheduler.start()
    for job_id in runner.JOBS:
        cfg = runner.get_setting(job_id)
        _apply(job_id, cfg)
        if cfg["enabled"] and runner.in_active_window(cfg) and _overdue(job_id, cfg):
            task = asyncio.create_task(_catch_up(job_id))
            _catchup_tasks.add(task)
            task.add_done_callback(_catchup_tasks.discard)
    log.info("scheduler started with jobs: %s", ", ".join(runner.JOBS))


async def stop() -> None:
    global _scheduler
    for task in list(_catchup_tasks):
        task.cancel()
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
