"""Job bookkeeping: every run is recorded in job_runs, overlapping runs are refused, and the active window is honoured."""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db import pg

log = logging.getLogger("jobs")


@dataclass
class JobDef:
    id: str
    title: str
    description: str
    func: Callable[[], Awaitable[dict]]
    default_interval_minutes: int
    active_from: time | None = None      # daily window in local time; None = always
    active_to: time | None = None


JOBS: dict[str, JobDef] = {}
_locks: dict[str, asyncio.Lock] = {}


def register(job: JobDef) -> JobDef:
    JOBS[job.id] = job
    return job


def ensure_job_settings() -> None:
    """Seed job_settings with each job's defaults. Existing rows (your edits) are never overwritten."""
    for j in JOBS.values():
        pg.execute(
            "INSERT INTO job_settings (job_id, enabled, interval_minutes, active_from, active_to) "
            "VALUES (%s, true, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING",
            (j.id, j.default_interval_minutes, j.active_from, j.active_to),
        )


def get_setting(job_id: str) -> dict:
    return pg.fetch_one("SELECT * FROM job_settings WHERE job_id = %s", (job_id,)) or {}


def in_active_window(cfg: dict, now: datetime | None = None) -> bool:
    start, end = cfg.get("active_from"), cfg.get("active_to")
    if not start or not end:
        return True
    t = (now or datetime.now(ZoneInfo(settings.timezone))).time()
    return start <= t <= end if start <= end else (t >= start or t <= end)   # window may wrap midnight


def is_running(job_id: str) -> bool:
    lock = _locks.get(job_id)
    return bool(lock and lock.locked())


def close_interrupted_runs() -> int:
    """Runs left 'running' by a crash or a PC shutdown are closed so the Jobs panel is truthful."""
    return pg.execute(
        "UPDATE job_runs SET status = 'error', finished_at = now(), error = 'interrupted (app stopped while running)' "
        "WHERE status = 'running'")


async def run_job(job_id: str, trigger: str = "schedule") -> dict | None:
    """Run one job and record it. Returns the job's result, or None if it was refused or failed."""
    job = JOBS[job_id]
    lock = _locks.setdefault(job_id, asyncio.Lock())
    if lock.locked():
        log.info("job %s already running; skipping %s run", job_id, trigger)
        return None
    async with lock:
        run = await asyncio.to_thread(
            pg.fetch_one, "INSERT INTO job_runs (job_id, trigger) VALUES (%s, %s) RETURNING id", (job_id, trigger))
        run_id = run["id"]
        try:
            result = await job.func() or {}
            status, error = "ok", None
        except asyncio.CancelledError:
            await asyncio.to_thread(
                pg.execute, "UPDATE job_runs SET status = 'error', finished_at = now(), error = 'cancelled' WHERE id = %s", (run_id,))
            raise
        except Exception as e:  # noqa: BLE001 - a job failure must never take the app down
            log.exception("job %s failed", job_id)
            result, status, error = {}, "error", f"{type(e).__name__}: {e}"
        added = int(result.pop("rows_added", 0) or 0)
        updated = int(result.pop("rows_updated", 0) or 0)
        if result.get("blocked") and status == "ok":
            status = "error"
            error = f"blocked: {result['blocked']}"
        await asyncio.to_thread(
            pg.execute,
            "UPDATE job_runs SET status = %s, finished_at = now(), rows_added = %s, rows_updated = %s, detail = %s, error = %s "
            "WHERE id = %s", (status, added, updated, json.dumps(result, default=str), error, run_id))
        return result if status == "ok" else None


async def scheduled_run(job_id: str) -> None:
    """Entry point APScheduler calls. Honours the enabled flag and the daily active window."""
    cfg = await asyncio.to_thread(get_setting, job_id)
    if not cfg.get("enabled", True) or not in_active_window(cfg):
        return
    await run_job(job_id, "schedule")
