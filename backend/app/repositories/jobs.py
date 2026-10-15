"""Scheduler state: per-job settings and the record of every run."""
import json
from datetime import datetime, time
from typing import Any

from app.db.database import Database, Row


def seed_settings(db: Database, job_id: str, interval_minutes: int, active_from: time | None, active_to: time | None) -> None:
    """Insert a job's defaults. An existing row (the user's edits) is never overwritten."""
    db.execute(
        "INSERT INTO job_settings (job_id, enabled, interval_minutes, active_from, active_to) "
        "VALUES (%s, true, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING",
        (job_id, interval_minutes, active_from, active_to))


def get_settings(db: Database, job_id: str) -> Row:
    return db.fetch_one("SELECT * FROM job_settings WHERE job_id = %s", (job_id,)) or {}


def update_settings(db: Database, job_id: str, enabled: bool, interval_minutes: int,
                    active_from: str | None, active_to: str | None) -> None:
    db.execute(
        "UPDATE job_settings SET enabled = %s, interval_minutes = %s, active_from = %s, active_to = %s, "
        "updated_at = now() WHERE job_id = %s",
        (enabled, interval_minutes, active_from, active_to, job_id))


def close_interrupted(db: Database) -> int:
    """Runs left 'running' by a crash or a PC shutdown are closed so the Jobs panel is truthful."""
    return db.execute(
        "UPDATE job_runs SET status = 'error', finished_at = now(), error = 'interrupted (app stopped while running)' "
        "WHERE status = 'running'")


def start_run(db: Database, job_id: str, trigger: str) -> int:
    row = db.fetch_one("INSERT INTO job_runs (job_id, trigger) VALUES (%s, %s) RETURNING id", (job_id, trigger))
    assert row is not None
    return int(row["id"])


def finish_run(db: Database, run_id: int, status: str, added: int, updated: int,
               detail: dict[str, Any], error: str | None) -> None:
    db.execute(
        "UPDATE job_runs SET status = %s, finished_at = now(), rows_added = %s, rows_updated = %s, detail = %s, error = %s "
        "WHERE id = %s", (status, added, updated, json.dumps(detail, default=str), error, run_id))


def cancel_run(db: Database, run_id: int) -> None:
    db.execute("UPDATE job_runs SET status = 'error', finished_at = now(), error = 'cancelled' WHERE id = %s", (run_id,))


def last_run(db: Database, job_id: str) -> Row | None:
    return db.fetch_one("SELECT * FROM job_runs WHERE job_id = %s ORDER BY started_at DESC LIMIT 1", (job_id,))


def last_ok(db: Database, job_id: str) -> datetime | None:
    row = db.fetch_one("SELECT max(finished_at) AS t FROM job_runs WHERE job_id = %s AND status = 'ok'", (job_id,))
    return row["t"] if row else None


def recent_runs(db: Database, limit: int) -> list[Row]:
    return db.fetch_all(
        "SELECT id, job_id, started_at, finished_at, status, trigger, rows_added, rows_updated, error "
        "FROM job_runs ORDER BY started_at DESC LIMIT %s", (limit,))
