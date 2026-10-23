"""Postgres access: a pooled read/write connection for the app and a read-only pool for generated SQL.

Everything here is synchronous (psycopg); async code calls it through asyncio.to_thread. One `Database` is created per
app (see `app.runtime.Runtime`) and handed to whatever needs it, so there is no module-level connection state.
"""
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

Row = DictRow


class DatabaseUnavailable(RuntimeError):
    """The pools are not open (Postgres was unreachable at startup)."""


class Database:
    def __init__(self, url: str, readonly_url: str, connect_timeout: float = 15, pool_size: int = 8,
                 pool_timeout: float = 30) -> None:
        """`pool_size` connections for read/write work; a request that cannot get one within `pool_timeout` seconds fails
        (the API turns that into a 503) rather than waiting for ever."""
        self._url = url
        self._timeout = connect_timeout
        self.pool_size = pool_size
        self._pool_timeout = pool_timeout
        self._readonly_url = readonly_url
        self._lock = threading.Lock()
        self._pool: ConnectionPool[Connection[Row]] | None = None
        self._ro_pool: ConnectionPool[Connection[Row]] | None = None

    def _open(self, url: str, name: str, max_size: int) -> ConnectionPool[Connection[Row]]:
        pool: ConnectionPool[Connection[Row]] = ConnectionPool(
            url, min_size=1, max_size=max_size, open=False, name=name, timeout=self._pool_timeout,
            kwargs={"row_factory": dict_row, "autocommit": False})
        try:
            pool.open(wait=True, timeout=self._timeout)
        except Exception:
            pool.close(timeout=1)       # do not leave its worker threads retrying in the background
            raise
        return pool

    def open(self) -> None:
        """Open the read/write pool. The read-only pool opens on first use, because its role is made by a migration."""
        with self._lock:
            if self._pool is None:
                self._pool = self._open(self._url, "lettings-rw", self.pool_size)

    def _get_ro_pool(self) -> ConnectionPool[Connection[Row]]:
        with self._lock:
            if self._ro_pool is None:
                self._ro_pool = self._open(self._readonly_url, "lettings-ro", 3)
            return self._ro_pool

    def close(self) -> None:
        with self._lock:
            for pool in (self._pool, self._ro_pool):
                if pool is not None:
                    pool.close()
            self._pool = self._ro_pool = None

    @contextmanager
    def conn(self) -> Iterator[Connection[Row]]:
        """Read/write connection; commits on success, rolls back on error."""
        if self._pool is None:
            raise DatabaseUnavailable("database is not open")
        with self._pool.connection() as c:
            yield c

    @contextmanager
    def ro_conn(self) -> Iterator[Connection[Row]]:
        """Connection for generated SQL: read-only role, read-only transaction, short timeout."""
        with self._get_ro_pool().connection() as c:
            yield c

    def fetch_all(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[Row]:
        with self.conn() as c:
            return c.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> Row | None:
        with self.conn() as c:
            return c.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> int:
        with self.conn() as c:
            return c.execute(sql, params).rowcount
