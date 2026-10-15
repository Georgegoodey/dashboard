"""Job runner and scheduler bookkeeping against a real database."""
import asyncio
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.db.database import Database
from app.jobs.runner import JobDef, JobRunner, in_active_window
from app.repositories import jobs as jobs_repo
from app.runtime import Runtime

pytestmark = pytest.mark.integration


def make_runtime(settings: Settings, db: Database, job_funcs: dict[str, Any]) -> Runtime:
    rt = Runtime(settings, db)
    rt.runner = JobRunner(rt, {k: JobDef(k, k.title(), "test job", f, 5) for k, f in job_funcs.items()})
    return rt


async def test_a_successful_run_is_recorded_with_counts(settings: Settings, db: Database) -> None:
    async def ok(rt: Runtime) -> dict[str, Any]:
        return {"rows_added": 4, "rows_updated": 2, "note": "hello"}

    rt = make_runtime(settings, db, {"ok": ok})
    assert await rt.runner.run_job("ok", "manual") == {"note": "hello"}
    run = jobs_repo.last_run(db, "ok")
    assert run and run["status"] == "ok" and run["rows_added"] == 4 and run["rows_updated"] == 2
    assert run["trigger"] == "manual" and run["detail"] == {"note": "hello"} and run["finished_at"]


async def test_a_failing_job_is_recorded_and_does_not_raise(settings: Settings, db: Database) -> None:
    async def boom(rt: Runtime) -> dict[str, Any]:
        raise RuntimeError("kaput")

    rt = make_runtime(settings, db, {"boom": boom})
    assert await rt.runner.run_job("boom") is None
    run = jobs_repo.last_run(db, "boom")
    assert run and run["status"] == "error" and run["error"] == "RuntimeError: kaput"


async def test_a_blocked_job_is_marked_as_an_error(settings: Settings, db: Database) -> None:
    async def blocked(rt: Runtime) -> dict[str, Any]:
        return {"blocked": "challenge page"}

    rt = make_runtime(settings, db, {"blocked": blocked})
    assert await rt.runner.run_job("blocked") is None
    run = jobs_repo.last_run(db, "blocked")
    assert run and run["status"] == "error" and run["error"] == "blocked: challenge page"


async def test_overlapping_runs_are_refused(settings: Settings, db: Database) -> None:
    gate = asyncio.Event()

    async def slow(rt: Runtime) -> dict[str, Any]:
        await gate.wait()
        return {}

    rt = make_runtime(settings, db, {"slow": slow})
    first = asyncio.create_task(rt.runner.run_job("slow"))
    await asyncio.sleep(0.2)
    assert rt.runner.is_running("slow")
    assert await rt.runner.run_job("slow") is None                         # refused, nothing recorded
    assert len(jobs_repo.recent_runs(db, 10)) == 1
    with pytest.raises(Conflict):
        rt.scheduler.run_now("slow")
    gate.set()
    await first
    assert not rt.runner.is_running("slow")


async def test_run_now_spawns_a_tracked_task_and_rejects_unknown_jobs(settings: Settings, db: Database) -> None:
    done = asyncio.Event()

    async def quick(rt: Runtime) -> dict[str, Any]:
        done.set()
        return {}

    rt = make_runtime(settings, db, {"quick": quick})
    with pytest.raises(NotFound):
        rt.scheduler.run_now("nope")
    rt.scheduler.run_now("quick")
    await asyncio.wait_for(done.wait(), 5)
    await asyncio.sleep(0.3)
    assert rt.scheduler._tasks == set()                                    # finished tasks are released
    assert jobs_repo.last_run(db, "quick")["status"] == "ok"               # type: ignore[index]


async def test_stopping_cancels_background_tasks(settings: Settings, db: Database) -> None:
    rt = make_runtime(settings, db, {})
    task = rt.scheduler.spawn_task(asyncio.sleep(60))
    await rt.scheduler.stop()
    await asyncio.sleep(0.05)
    assert task.cancelled()


async def test_scheduled_runs_honour_enabled_and_window(settings: Settings, db: Database) -> None:
    async def tick(rt: Runtime) -> dict[str, Any]:
        return {}

    rt = make_runtime(settings, db, {"tick": tick})
    rt.runner.ensure_settings()
    jobs_repo.update_settings(db, "tick", False, 5, None, None)
    await rt.runner.scheduled_run("tick")
    assert jobs_repo.last_run(db, "tick") is None                          # disabled: skipped
    jobs_repo.update_settings(db, "tick", True, 5, None, None)
    await rt.runner.scheduled_run("tick")
    assert jobs_repo.last_run(db, "tick") is not None


async def test_start_seeds_settings_and_closes_interrupted_runs(settings: Settings, db: Database) -> None:
    async def tick(rt: Runtime) -> dict[str, Any]:
        return {}

    rt = make_runtime(settings, db, {"tick": tick})
    stale = jobs_repo.start_run(db, "tick", "schedule")
    live = Settings(**{**settings.model_dump(), "scheduler_enabled": True})
    rt.settings = live
    await rt.scheduler.start()
    try:
        assert jobs_repo.get_settings(db, "tick")["interval_minutes"] == 5
        run = db.fetch_one("SELECT status, error FROM job_runs WHERE id = %s", (stale,))
        assert run and run["status"] == "error" and "interrupted" in run["error"]
        assert rt.scheduler.next_run_time("tick") is not None
        rt.scheduler.reschedule("tick")
        assert db.fetch_one("SELECT count(*) AS n FROM apscheduler_jobs") == {"n": 1}      # replace_existing: never duplicated
    finally:
        await rt.scheduler.stop()


def test_active_window_including_one_that_wraps_midnight() -> None:
    tz = "Europe/London"
    cfg = {"active_from": time(7, 0), "active_to": time(22, 0)}
    assert in_active_window(cfg, tz, datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo(tz)))
    assert not in_active_window(cfg, tz, datetime(2026, 10, 20, 23, 0, tzinfo=ZoneInfo(tz)))
    night = {"active_from": time(22, 0), "active_to": time(6, 0)}
    assert in_active_window(night, tz, datetime(2026, 10, 20, 23, 30, tzinfo=ZoneInfo(tz)))
    assert in_active_window(night, tz, datetime(2026, 10, 20, 5, 0, tzinfo=ZoneInfo(tz)))
    assert not in_active_window(night, tz, datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo(tz)))
    assert in_active_window({}, tz)
