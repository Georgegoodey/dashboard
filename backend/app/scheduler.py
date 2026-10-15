"""APScheduler 3.x inside the app: AsyncIOScheduler with jobs persisted in Postgres.

Rules this follows (from the APScheduler docs): every job has a stable id and replace_existing=True, so a restart never
duplicates jobs; one scheduler process only; coalesce=True so a stretch of missed runs becomes one run.
Because the PC may sleep, each job is state-driven, and on startup any job overdue by its interval runs once ("catch-up").
"""
import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.errors import Conflict, NotFound
from app.jobs.runner import in_active_window
from app.repositories import jobs as jobs_repo

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("scheduler")


class SchedulerService:
    def __init__(self, runtime: "Runtime") -> None:
        self._rt = runtime
        self._scheduler: AsyncIOScheduler | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Run a coroutine in the background. The service keeps a reference so it is not garbage-collected mid-run,
        and cancels whatever is still running when the app stops."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def run_now(self, job_id: str) -> None:
        """Start a job immediately in the background (the 'Run now' button)."""
        runner = self._rt.runner
        if job_id not in runner.jobs:
            raise NotFound("Unknown job")
        if runner.is_running(job_id):
            raise Conflict("Already running")
        self.spawn_task(runner.run_job(job_id, "manual"))

    def _trigger(self, minutes: int) -> IntervalTrigger:
        return IntervalTrigger(minutes=max(int(minutes), 1), timezone=ZoneInfo(self._rt.settings.timezone))

    def _apply(self, job_id: str, cfg: dict[str, Any]) -> None:
        """Create or update the scheduler entry for a job from its settings row."""
        assert self._scheduler is not None
        self._scheduler.add_job("app.jobs.runner:scheduled_run", trigger=self._trigger(cfg["interval_minutes"]),
                                args=[job_id], id=job_id, name=self._rt.runner.jobs[job_id].title, replace_existing=True)
        if not cfg["enabled"]:
            self._scheduler.pause_job(job_id)

    def reschedule(self, job_id: str) -> None:
        """Call after the job's settings change in the UI."""
        if self._scheduler is not None:
            self._apply(job_id, self._rt.runner.get_setting(job_id))

    def next_run_time(self, job_id: str) -> datetime | None:
        if self._scheduler is None:
            return None
        job = self._scheduler.get_job(job_id)
        return getattr(job, "next_run_time", None) if job else None

    def _overdue(self, job_id: str, cfg: dict[str, Any]) -> bool:
        t = jobs_repo.last_ok(self._rt.db, job_id)
        if t is None:
            return True
        return datetime.now(t.tzinfo) - t > timedelta(minutes=cfg["interval_minutes"])

    async def _catch_up(self, job_id: str) -> None:
        await asyncio.sleep(3)             # let the app finish starting
        await self._rt.runner.run_job(job_id, "catch-up")

    async def start(self) -> None:
        if self._scheduler is not None:
            return
        runner = self._rt.runner
        runner.ensure_settings()
        closed = runner.close_interrupted_runs()
        if closed:
            log.info("closed %s run(s) interrupted by the last shutdown", closed)

        self._scheduler = AsyncIOScheduler(
            timezone=ZoneInfo(self._rt.settings.timezone),
            jobstores={"default": SQLAlchemyJobStore(url=self._rt.settings.sqlalchemy_url, tablename="apscheduler_jobs")},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 6 * 3600},
        )
        self._scheduler.start()
        for job_id in runner.jobs:
            cfg = runner.get_setting(job_id)
            self._apply(job_id, cfg)
            if cfg["enabled"] and in_active_window(cfg, self._rt.settings.timezone) and self._overdue(job_id, cfg):
                self.spawn_task(self._catch_up(job_id))
        log.info("scheduler started with jobs: %s", ", ".join(runner.jobs))

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
