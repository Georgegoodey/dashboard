"""Commute routes: which (property, profile) pairs still need a TfL journey, and storing the results."""
import json
from datetime import date
from typing import Any

from app.db.database import Database, Row

ROUTE_TTL_DAYS = 30
FAILED_TTL_DAYS = 1       # a pair TfL could not route is retried tomorrow, not every run

_PENDING = """
        FROM properties p
        CROSS JOIN commute_profiles cp
        JOIN places pl ON pl.kind = cp.place_kind AND pl.geom IS NOT NULL
        WHERE cp.enabled AND p.geom IS NOT NULL
          AND EXISTS (SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')
          AND NOT EXISTS (SELECT 1 FROM commute_routes r
                          WHERE r.property_id = p.id AND r.profile_id = cp.id AND r.expires_at > now())
"""


def pending_pairs(db: Database, limit: int) -> list[Row]:
    """Active properties x enabled profiles (whose place has a location) with no fresh route yet, newest first."""
    return db.fetch_all(
        "SELECT p.id AS property_id, ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon, "
        "cp.id AS profile_id, cp.slug, cp.direction, cp.anchor, cp.local_time, cp.weekday, "
        "ST_Y(pl.geom::geometry) AS place_lat, ST_X(pl.geom::geometry) AS place_lon "
        f"{_PENDING} ORDER BY p.first_seen DESC, cp.id LIMIT %s", (limit,))


def count_pending(db: Database) -> int:
    row = db.fetch_one(f"SELECT count(*) AS n {_PENDING}")
    return int(row["n"]) if row else 0


def save_route(db: Database, pair: Row, ref_date: date, result: dict[str, Any] | None) -> None:
    ttl = ROUTE_TTL_DAYS if result else FAILED_TTL_DAYS
    r = result or {}
    db.execute(
        "INSERT INTO commute_routes (property_id, profile_id, provider, ref_date, duration_min, walk_min, transfers, "
        "fare_pence, summary, journey, expires_at) "
        "VALUES (%s, %s, 'tfl', %s, %s, %s, %s, %s, %s, %s, now() + make_interval(days => %s)) "
        "ON CONFLICT (property_id, profile_id, provider, ref_date) DO UPDATE SET duration_min = EXCLUDED.duration_min, "
        "walk_min = EXCLUDED.walk_min, transfers = EXCLUDED.transfers, fare_pence = EXCLUDED.fare_pence, "
        "summary = EXCLUDED.summary, journey = EXCLUDED.journey, fetched_at = now(), expires_at = EXCLUDED.expires_at",
        (pair["property_id"], pair["profile_id"], ref_date, r.get("duration_min"), r.get("walk_min"), r.get("transfers"),
         r.get("fare_pence"), r.get("summary") or ("No journey found" if not result else None),
         json.dumps(r) if r else None, ttl))


def count_api_call(db: Database, provider: str = "tfl", n: int = 1) -> None:
    db.execute("INSERT INTO api_usage (provider, day, calls) VALUES (%s, current_date, %s) "
               "ON CONFLICT (provider, day) DO UPDATE SET calls = api_usage.calls + EXCLUDED.calls", (provider, n))
