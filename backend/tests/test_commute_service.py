"""compute_pending: concurrency against a slow API, throttling, and the time budget."""
import asyncio
import time
from typing import Any

import pytest

from app.commute.tfl import Throttled
from app.db.database import Database
from app.repositories import commute_points, commutes, listings
from app.services import commute as service
from tests.test_repositories import raw

pytestmark = pytest.mark.integration

JOURNEY = {"duration_min": 30, "walk_min": 5, "transfers": 1, "fare_pence": 280, "summary": "x"}


class FakeTfl:
    """Every journey takes 0.3 s to answer, like the real API."""
    concurrency = 5
    app_key = "k"
    calls = 0
    in_flight = 0
    peak = 0
    throttle_after: int | None = None

    def __init__(self, key: str | None) -> None:
        type(self).calls = type(self).in_flight = type(self).peak = 0

    async def journey(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        cls = type(self)
        cls.calls += 1
        if cls.throttle_after is not None and cls.calls > cls.throttle_after:
            raise Throttled("HTTP 429")
        cls.in_flight += 1
        cls.peak = max(cls.peak, cls.in_flight)
        await asyncio.sleep(0.3)
        cls.in_flight -= 1
        return JOURNEY


@pytest.fixture
def seeded(db: Database, monkeypatch: pytest.MonkeyPatch) -> Database:
    monkeypatch.setattr(service, "TflClient", FakeTfl)
    FakeTfl.throttle_after = None
    commute_points.add(db, "Work", None, "EC2R 8AH", 51.5, -0.09, [commute_points.TO_POINT, commute_points.FROM_POINT])
    for i in range(10):
        listings.insert_new(db, raw(str(i), address=f"{i} Road"))          # 10 properties x 2 work profiles
    return db


async def test_journeys_run_concurrently_so_a_key_actually_speeds_things_up(seeded: Database) -> None:
    started = time.monotonic()
    stats = await service.compute_pending(seeded, tfl_key="k", timezone="Europe/London")
    elapsed = time.monotonic() - started
    assert stats["computed"] == 20 and stats["commute_pending"] == 0 and stats["concurrency"] == 5
    assert FakeTfl.peak == 5
    assert elapsed < 20 * 0.3 / 2                                          # one at a time would take 6 s


async def test_a_throttle_response_stops_every_worker_and_keeps_what_was_done(seeded: Database) -> None:
    FakeTfl.throttle_after = 6
    stats = await service.compute_pending(seeded, tfl_key="k", timezone="Europe/London")
    assert "throttled" in stats and 0 < stats["computed"] <= 6
    assert commutes.count_pending(seeded) == 20 - stats["computed"]
    assert FakeTfl.calls < 20                                              # nothing kept hammering after the 429


async def test_the_time_budget_is_respected(seeded: Database) -> None:
    stats = await service.compute_pending(seeded, tfl_key="k", timezone="Europe/London", budget_seconds=0)
    assert stats["computed"] == 0 and stats["commute_pending"] == 20
