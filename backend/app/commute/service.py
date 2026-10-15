"""Compute and cache commute routes for properties, driven by the profiles in Settings."""
import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.commute.tfl import Throttled, TflClient, next_weekday
from app.core.config import settings
from app.db import pg

ROUTE_TTL_DAYS = 30
FAILED_TTL_DAYS = 1       # a pair TfL could not route is retried tomorrow, not every run


def pending_pairs(limit: int) -> list[dict]:
    """Active properties x enabled profiles (whose place has a location) with no fresh route yet, newest first."""
    return pg.fetch_all(
        """
        SELECT p.id AS property_id, ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon,
               cp.id AS profile_id, cp.slug, cp.direction, cp.anchor, cp.local_time, cp.weekday,
               ST_Y(pl.geom::geometry) AS place_lat, ST_X(pl.geom::geometry) AS place_lon
        FROM properties p
        CROSS JOIN commute_profiles cp
        JOIN places pl ON pl.kind = cp.place_kind AND pl.geom IS NOT NULL
        WHERE cp.enabled AND p.geom IS NOT NULL
          AND EXISTS (SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')
          AND NOT EXISTS (SELECT 1 FROM commute_routes r
                          WHERE r.property_id = p.id AND r.profile_id = cp.id AND r.expires_at > now())
        ORDER BY p.first_seen DESC, cp.id
        LIMIT %s
        """,
        (limit,),
    )


def count_pending() -> int:
    row = pg.fetch_one(
        """
        SELECT count(*) AS n FROM properties p
        CROSS JOIN commute_profiles cp
        JOIN places pl ON pl.kind = cp.place_kind AND pl.geom IS NOT NULL
        WHERE cp.enabled AND p.geom IS NOT NULL
          AND EXISTS (SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')
          AND NOT EXISTS (SELECT 1 FROM commute_routes r
                          WHERE r.property_id = p.id AND r.profile_id = cp.id AND r.expires_at > now())
        """)
    return row["n"] if row else 0


def save_route(pair: dict, ref_date, result: dict | None) -> None:
    ttl = ROUTE_TTL_DAYS if result else FAILED_TTL_DAYS
    r = result or {}
    pg.execute(
        "INSERT INTO commute_routes (property_id, profile_id, provider, ref_date, duration_min, walk_min, transfers, "
        "fare_pence, summary, journey, expires_at) VALUES (%s, %s, 'tfl', %s, %s, %s, %s, %s, %s, %s, now() + make_interval(days => %s)) "
        "ON CONFLICT (property_id, profile_id, provider, ref_date) DO UPDATE SET duration_min = EXCLUDED.duration_min, "
        "walk_min = EXCLUDED.walk_min, transfers = EXCLUDED.transfers, fare_pence = EXCLUDED.fare_pence, "
        "summary = EXCLUDED.summary, journey = EXCLUDED.journey, fetched_at = now(), expires_at = EXCLUDED.expires_at",
        (pair["property_id"], pair["profile_id"], ref_date, r.get("duration_min"), r.get("walk_min"), r.get("transfers"),
         r.get("fare_pence"), r.get("summary") or ("No journey found" if not result else None), json.dumps(r) if r else None, ttl),
    )


def count_api_call(n: int = 1) -> None:
    pg.execute("INSERT INTO api_usage (provider, day, calls) VALUES ('tfl', current_date, %s) "
               "ON CONFLICT (provider, day) DO UPDATE SET calls = api_usage.calls + EXCLUDED.calls", (n,))


async def compute_pending(budget_seconds: int = 240, batch: int = 400) -> dict:
    """Fetch routes for pending pairs within a time budget. Safe to run repeatedly; it only does what is missing."""
    tfl = TflClient()
    deadline = time.monotonic() + budget_seconds
    pairs = await asyncio.to_thread(pending_pairs, batch)
    stats: dict = {"computed": 0, "no_route": 0, "errors": 0, "keyed": bool(tfl.app_key)}
    tz = ZoneInfo(settings.timezone)
    async with httpx.AsyncClient(timeout=30) as client:
        for pair in pairs:
            if time.monotonic() > deadline:
                break
            ref = next_weekday(pair["weekday"])
            when = datetime.combine(ref, pair["local_time"], tzinfo=tz)
            prop = f'{pair["lat"]},{pair["lon"]}'
            place = f'{pair["place_lat"]},{pair["place_lon"]}'
            origin, dest = (prop, place) if pair["direction"] == "to_place" else (place, prop)
            try:
                result = await tfl.journey(client, origin, dest, when, arrive=pair["anchor"] == "arrive_by")
            except Throttled as e:
                stats["throttled"] = str(e)
                break
            except httpx.HTTPError:
                stats["errors"] += 1
                continue
            await asyncio.to_thread(save_route, pair, ref, result)
            await asyncio.to_thread(count_api_call)
            stats["computed" if result else "no_route"] += 1
    stats["rows_added"] = stats["computed"]
    stats["commute_pending"] = await asyncio.to_thread(count_pending)
    return stats
