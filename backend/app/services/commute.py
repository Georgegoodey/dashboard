"""Compute and cache commute routes for properties, driven by the profiles in Settings."""
import asyncio
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.commute.tfl import TflClient, Throttled, next_weekday
from app.db.database import Database, Row
from app.repositories import commutes


async def compute_pending(db: Database, *, tfl_key: str | None, timezone: str,
                          budget_seconds: int = 240, batch: int = 1500) -> dict[str, Any]:
    """Fetch routes for pending pairs within a time budget. Safe to run repeatedly; it only does what is missing."""
    tfl = TflClient(tfl_key)
    deadline = time.monotonic() + budget_seconds
    pairs = await asyncio.to_thread(commutes.pending_pairs, db, batch)
    stats: dict[str, Any] = {"computed": 0, "no_route": 0, "errors": 0, "keyed": bool(tfl.app_key)}
    tz = ZoneInfo(timezone)
    queue: asyncio.Queue[Row] = asyncio.Queue()
    for pair in pairs:
        queue.put_nowait(pair)
    stop = asyncio.Event()                      # set when TfL throttles us or the time budget is spent

    async def worker(client: httpx.AsyncClient) -> None:
        while not stop.is_set():
            if time.monotonic() > deadline:
                stop.set()
                return
            try:
                pair = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            ref = next_weekday(pair["weekday"], tz=timezone)
            when = datetime.combine(ref, pair["local_time"], tzinfo=tz)
            prop = f'{pair["lat"]},{pair["lon"]}'
            place = f'{pair["place_lat"]},{pair["place_lon"]}'
            origin, dest = (prop, place) if pair["direction"] == "to_place" else (place, prop)
            try:
                result = await tfl.journey(client, origin, dest, when, arrive=pair["anchor"] == "arrive_by")
            except Throttled as e:
                stats["throttled"] = str(e)
                stop.set()
                return
            except httpx.HTTPError:
                stats["errors"] += 1
                continue
            await asyncio.to_thread(commutes.save_route, db, pair, ref, result)
            await asyncio.to_thread(commutes.count_api_call, db)
            stats["computed" if result else "no_route"] += 1

    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=tfl.concurrency)) as client:
        await asyncio.gather(*(worker(client) for _ in range(tfl.concurrency)))
    stats["concurrency"] = tfl.concurrency
    stats["rows_added"] = stats["computed"]
    stats["commute_pending"] = await asyncio.to_thread(commutes.count_pending, db)
    return stats
