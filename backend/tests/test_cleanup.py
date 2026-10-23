"""Small robustness fixes: shared HTTP client, per-request error counter, connection pool limits, concurrent migrations."""
import contextvars
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread
import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import tools
from app.core.config import Settings
from app.core.errors import InvalidInput
from app.db import migrate
from app.db.database import Database
from app.main import create_app
from app.runtime import Runtime
from app.services import postcodes

# ── a shared HTTP client for postcode lookups ───────────────────────────────────────────────────────────────────

async def test_locate_uses_the_client_it_is_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "SW11" in str(request.url):
            return httpx.Response(200, json={"result": {"latitude": 51.5, "longitude": -0.17, "admin_district": "Wandsworth"}})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await postcodes.locate(client, "sw117fd")
        assert found == {"postcode": "SW11 7FD", "lat": 51.5, "lon": -0.17, "borough": "Wandsworth"}
        await postcodes.locate(client, "SW11 7FD")                                    # the same client, again
        with pytest.raises(InvalidInput, match="not a full UK postcode"):
            await postcodes.locate(client, "nonsense")
        with pytest.raises(InvalidInput, match="does not know"):
            await postcodes.locate(client, "ZZ99 9ZZ")
    assert len(seen) == 3


@pytest.mark.integration
def test_the_runtime_has_one_client_and_closes_it(settings: Settings, db: Database) -> None:
    rt = Runtime(settings)                      # its own database: stopping a runtime closes the one it holds
    assert isinstance(rt.http, httpx.AsyncClient) and not rt.http.is_closed
    with TestClient(create_app(settings, rt)):
        pass
    assert rt.http.is_closed


# ── the agent's failed-query counter ────────────────────────────────────────────────────────────────────────────

def test_the_error_counter_is_made_per_request_not_shared() -> None:
    def fresh() -> list[int]:
        return tools._error_counter()

    token = tools._sql_errors.set(None)                                       # an earlier test may have started a request
    try:
        a = contextvars.copy_context().run(fresh)
        b = contextvars.copy_context().run(fresh)
        assert a == [0] and b == [0] and a is not b                          # no shared default list
        assert tools._sql_errors.get() is None                                # nothing leaked into this context
    finally:
        tools._sql_errors.reset(token)


def test_reset_starts_a_new_count_that_threads_of_the_request_share() -> None:
    ctx = contextvars.copy_context()
    counter = ctx.run(tools.reset_sql_errors)
    seen: list[list[int]] = []
    worker = threading.Thread(target=lambda: seen.append(ctx.copy().run(tools._error_counter)))       # a worker gets a context copy
    worker.start()
    worker.join()
    seen[0][0] += 1
    assert counter == [1]                                                     # the worker's increment is the request's count
    assert ctx.run(tools.reset_sql_errors) == [0]                             # the next request starts again


# ── connection pool limits ──────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def small_pool(settings: Settings) -> Iterator[TestClient]:
    small = settings.model_copy(update={"db_pool_size": 2, "db_pool_timeout": 0.3})
    with TestClient(create_app(small)) as client:
        yield client


@pytest.mark.integration
def test_the_api_threads_are_held_to_the_pool_size(small_pool: TestClient) -> None:
    limit = small_pool.portal.call(lambda: anyio.to_thread.current_default_thread_limiter().total_tokens)  # type: ignore[union-attr]
    assert limit == 2


@pytest.mark.integration
def test_a_busy_pool_answers_503_after_the_wait_instead_of_hanging(small_pool: TestClient) -> None:
    db: Database = small_pool.app.state.runtime.db  # type: ignore[attr-defined]
    assert db.pool_size == 2 and small_pool.get("/api/areas").status_code == 200
    with db.conn(), db.conn():                                               # every connection is in use
        response = small_pool.get("/api/areas")
    assert response.status_code == 503 and "PoolTimeout" in response.json()["detail"]
    assert small_pool.get("/api/areas").status_code == 200                    # and it recovers once they are free


def test_pool_settings_default_to_the_old_size_and_a_shorter_wait() -> None:
    s = Settings()
    assert (s.db_pool_size, s.db_pool_timeout) == (8, 10)


# ── migrations from two processes at once ───────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_two_starts_at_the_same_moment_migrate_once(postgres_urls: tuple[str, str]) -> None:
    import psycopg

    admin = psycopg.connect(postgres_urls[0], autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS racetest WITH (FORCE)")
    admin.execute("CREATE DATABASE racetest")
    admin.close()
    url = postgres_urls[0].rsplit("/", 1)[0] + "/racetest"
    db = Database(url, postgres_urls[1].rsplit("/", 1)[0] + "/racetest")
    db.open()
    try:
        sqlalchemy_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        start = threading.Barrier(2)

        def boot() -> list[str]:
            start.wait()
            return migrate.upgrade(db, sqlalchemy_url)

        with ThreadPoolExecutor(2) as pool:
            results = [f.result(timeout=120) for f in [pool.submit(boot), pool.submit(boot)]]
        applied = sorted(results, key=len)
        assert applied[0] == [] and applied[1][0] == "0001" and applied[1][-1] == migrate.current_revision(db)   # one did it all
        assert db.fetch_one("SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory'") == {"n": 0}      # and the lock is gone
    finally:
        db.close()
