"""Postgres access: a pooled read/write connection for the app and a read-only pool for generated SQL.

Everything here is synchronous (psycopg); async code calls it through asyncio.to_thread.
"""
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_lock = threading.Lock()
_pool: ConnectionPool | None = None
_ro_pool: ConnectionPool | None = None


def _open(url: str, name: str, max_size: int) -> ConnectionPool:
    pool = ConnectionPool(url, min_size=1, max_size=max_size, open=False, name=name,
                          kwargs={"row_factory": dict_row, "autocommit": False})
    pool.open(wait=True, timeout=15)
    return pool


def init_pools() -> None:
    """Open the read/write pool. The read-only pool opens on first use, because its role is created by a migration."""
    global _pool
    with _lock:
        if _pool is None:
            _pool = _open(settings.database_url, "lettings-rw", 8)


def _get_ro_pool() -> ConnectionPool:
    global _ro_pool
    with _lock:
        if _ro_pool is None:
            _ro_pool = _open(settings.readonly_database_url, "lettings-ro", 3)
        return _ro_pool


def close_pools() -> None:
    global _pool, _ro_pool
    with _lock:
        for pool in (_pool, _ro_pool):
            if pool is not None:
                pool.close()
        _pool = _ro_pool = None


@contextmanager
def conn() -> Iterator[Connection]:
    """Read/write connection; commits on success, rolls back on error."""
    assert _pool is not None, "database pools not initialised"
    with _pool.connection() as c:
        yield c


@contextmanager
def ro_conn() -> Iterator[Connection]:
    """Connection for generated SQL: read-only role, read-only transaction, short timeout."""
    with _get_ro_pool().connection() as c:
        yield c


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def execute(sql: str, params: Any = None) -> int:
    with conn() as c:
        return c.execute(sql, params).rowcount


def migrate() -> list[str]:
    """Apply any migrations/*.sql not yet recorded, in filename order. Returns the versions applied."""
    applied: list[str] = []
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in done:
            continue
        with conn() as c:  # one transaction per migration
            c.execute(path.read_text(encoding="utf-8"))
            c.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
        applied.append(path.stem)
    return applied
