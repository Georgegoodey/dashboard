"""Scheduler: job list and settings, run now, and run history."""
from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import Rt
from app.core.errors import NotFound
from app.repositories import commutes, jobs

router = APIRouter(prefix="/api")


class JobIn(BaseModel):
    enabled: bool
    interval_minutes: int = Field(ge=1, le=60 * 24 * 7)
    active_from: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    active_to: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


@router.get("/jobs")
def list_jobs(rt: Rt) -> list[dict[str, Any]]:
    out = []
    for job in rt.runner.jobs.values():
        cfg = rt.runner.get_setting(job.id)
        last = jobs.last_run(rt.db, job.id)
        out.append({
            "id": job.id, "title": job.title, "description": job.description,
            "enabled": cfg.get("enabled", True),
            "interval_minutes": cfg.get("interval_minutes", job.default_interval_minutes),
            "active_from": _hhmm(cfg.get("active_from")), "active_to": _hhmm(cfg.get("active_to")),
            "running": rt.runner.is_running(job.id),
            "next_run": _iso(rt.scheduler.next_run_time(job.id)),
            "last_ok": _iso(jobs.last_ok(rt.db, job.id)),
            "last_run": None if not last else {
                "started_at": _iso(last["started_at"]), "finished_at": _iso(last["finished_at"]),
                "status": last["status"], "trigger": last["trigger"], "rows_added": last["rows_added"],
                "rows_updated": last["rows_updated"], "detail": last["detail"], "error": last["error"]},
        })
    return out


@router.put("/jobs/{job_id}")
def update_job(job_id: str, body: JobIn, rt: Rt) -> Any:
    if job_id not in rt.runner.jobs:
        raise NotFound("Unknown job")
    jobs.update_settings(rt.db, job_id, body.enabled, body.interval_minutes, body.active_from, body.active_to)
    rt.scheduler.reschedule(job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/run", status_code=202)
async def run_job_now(job_id: str, rt: Rt) -> Any:
    rt.scheduler.run_now(job_id)
    return {"started": job_id}


@router.get("/jobs/runs")
def recent_runs(rt: Rt, limit: int = Query(30, le=200)) -> Any:
    return [{**r, "started_at": _iso(r["started_at"]), "finished_at": _iso(r["finished_at"])}
            for r in jobs.recent_runs(rt.db, limit)]


@router.get("/status")
def status(rt: Rt) -> Any:
    from app.repositories import properties

    row = dict(properties.counts(rt.db))
    row["commute_pending"] = commutes.count_pending(rt.db)
    return row
