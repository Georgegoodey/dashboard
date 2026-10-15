"""TfL Unified API journey planner: public-transport time, walking, changes and fare from a letting to a place.

One request per origin and destination pair (verified from TfL's swagger). `timeIs` can be Arriving or Departing, which
is what the commute profiles use ("arrive by 09:00", "leave at 18:00").
"""
import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.tfl.gov.uk"
WALKING = {"walking"}


class Throttled(Exception):
    """TfL asked us to slow down (HTTP 420 or 429). Stop for this run."""


def next_weekday(weekday: int, today: date | None = None, tz: str = "Europe/London") -> date:
    """The next date strictly after today that falls on `weekday` (0 = Monday), in London time."""
    today = today or datetime.now(ZoneInfo(tz)).date()
    return today + timedelta(days=((weekday - today.weekday() - 1) % 7) + 1)


def _leg_text(leg: dict) -> str:
    mode = (leg.get("mode") or {}).get("name", "")
    summary = (leg.get("instruction") or {}).get("summary") or mode.title()
    return f"{summary} ({leg.get('duration', 0)}m)"


def parse_journey(journey: dict) -> dict:
    """Reduce one TfL journey to the fields the app stores."""
    legs = journey.get("legs") or []
    walk = sum(int(leg.get("duration") or 0) for leg in legs if (leg.get("mode") or {}).get("name") in WALKING)
    vehicle_legs = [leg for leg in legs if (leg.get("mode") or {}).get("name") not in WALKING]
    fare = (journey.get("fare") or {}).get("totalCost")
    return {
        "duration_min": int(journey["duration"]),
        "walk_min": walk,
        "transfers": max(len(vehicle_legs) - 1, 0),
        "fare_pence": int(fare) if fare is not None else None,
        "summary": " > ".join(_leg_text(leg) for leg in legs),
        "start": journey.get("startDateTime"),
        "arrival": journey.get("arrivalDateTime"),
    }


def best_journey(payload: dict) -> dict | None:
    """The shortest journey TfL offers, parsed; None when it found no route."""
    journeys = [j for j in payload.get("journeys") or [] if j.get("duration") is not None]
    if not journeys:
        return None
    return parse_journey(min(journeys, key=lambda j: j["duration"]))


class TflClient:
    """Paces requests (5 a second with a key, 1 a second without) and stops cleanly when throttled."""

    def __init__(self, app_key: str | None = None):
        self.app_key = app_key or None
        self.min_interval = 0.2 if self.app_key else 1.0
        # requests start no faster than min_interval, but a journey takes a second or more to answer, so with a key
        # several must be in flight at once to actually reach 5 a second
        self.concurrency = 12 if self.app_key else 1
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def _pace(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + self.min_interval

    async def journey(self, client: httpx.AsyncClient, origin: str, destination: str, when: datetime, arrive: bool) -> dict | None:
        """origin and destination are 'lat,lon' strings. `when` is local time; `arrive` means arrive-by rather than depart-at."""
        params: dict[str, Any] = {
            "date": when.strftime("%Y%m%d"), "time": when.strftime("%H%M"),
            "timeIs": "Arriving" if arrive else "Departing", "journeyPreference": "LeastTime",
        }
        if self.app_key:
            params["app_key"] = self.app_key
        await self._pace()
        r = await client.get(f"{BASE}/Journey/JourneyResults/{origin}/to/{destination}", params=params,
                             headers={"User-Agent": "lettings-app"})
        if r.status_code in (420, 429):
            raise Throttled(f"TfL returned HTTP {r.status_code}")
        if r.status_code == 404:          # "no journey found" style responses
            return None
        r.raise_for_status()
        return best_journey(r.json())
