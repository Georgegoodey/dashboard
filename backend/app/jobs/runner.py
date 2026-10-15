"""Job bookkeeping: every run is recorded in job_runs, overlapping runs are refused, and the active window is honoured."""
import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app.core.logging import run_id_var
from app.db.database import Database, Row
from app.repositories import jobs as jobs_repo

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("jobs")


@dataclass
class JobDef:
    id: str
    title: str
    description: str
    func: Callable[["Runtime"], Awaitable[dict[str, Any]]]
    default_interval_minutes: int
    active_from: time | None = None      # daily window in local time; None = always
    active_to: time | None = None


def in_active_window(cfg: Mapping[str, Any], timezone: str, now: datetime | None = None) -> bool:
    start, end = cfg.get("active_from"), cfg.get("active_to")
    if not start or not end:
        return True
    t = (now or datetime.now(ZoneInfo(timezone))).time()
    inside: bool = start <= t <= end if start <= end else (t >= start or t <= end)   # window may wrap midnight
    return inside


class JobRunner:
    def __init__(self, runtime: "Runtime", jobs: Mapping[str, JobDef]) -> None:
        self._rt = runtime
        self.jobs = jobs
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def _db(self) -> Database:
        return self._rt.db

    def ensure_settings(self) -> None:
        """Seed job_settings with each job's defaults. Existing rows (the user's edits) are never overwritten."""
        for j in self.jobs.values():
            jobs_repo.seed_settings(self._db, j.id, j.default_interval_minutes, j.active_from, j.active_to)

    def get_setting(self, job_id: str) -> Row:
        return jobs_repo.get_settings(self._db, job_id)

    def is_running(self, job_id: str) -> bool:
        lock = self._locks.get(job_id)
        return bool(lock and lock.locked())

    def close_interrupted_runs(self) -> int:
        return jobs_repo.close_interrupted(self._db)

    async def run_job(self, job_id: str, trigger: str = "schedule") -> dict[str, Any] | None:
        """Run one job and record it. Returns the job's result, or None if it was refused or failed."""
        job = self.jobs[job_id]
        lock = self._locks.setdefault(job_id, asyncio.Lock())
        if lock.locked():
            log.info("job %s already running; skipping %s run", job_id, trigger)
            return None
        async with lock:
            run_id = await asyncio.to_thread(jobs_repo.start_run, self._db, job_id, trigger)
            token = run_id_var.set(f"{job_id}#{run_id}")
            try:
                log.info("job %s started (%s)", job_id, trigger)
                try:
                    result = await job.func(self._rt) or {}
                    status, error = "ok", None
                except asyncio.CancelledError:
                    await asyncio.to_thread(jobs_repo.cancel_run, self._db, run_id)
                    raise
                except Exception as e:
                    log.exception("job %s failed", job_id)
                    result, status, error = {}, "error", f"{type(e).__name__}: {e}"
                added = int(result.pop("rows_added", 0) or 0)
                updated = int(result.pop("rows_updated", 0) or 0)
                if result.get("blocked") and status == "ok":
                    status = "error"
                    error = f"blocked: {result['blocked']}"
                await asyncio.to_thread(jobs_repo.finish_run, self._db, run_id, status, added, updated, result, error)
                log.info("job %s finished: %s (+%s, ~%s)", job_id, status, added, updated)
                return result if status == "ok" else None
            finally:
                run_id_var.reset(token)

    async def scheduled_run(self, job_id: str) -> None:
        """What APScheduler triggers. Honours the enabled flag and the daily active window."""
        cfg = await asyncio.to_thread(self.get_setting, job_id)
        if not cfg.get("enabled", True) or not in_active_window(cfg, self._rt.settings.timezone):
            return
        await self.run_job(job_id, "schedule")


async def scheduled_run(job_id: str) -> None:
    """Module-level entry point: APScheduler stores jobs as the string 'app.jobs.runner:scheduled_run'."""
    from app.runtime import get_runtime

    await get_runtime().runner.scheduled_run(job_id)
