"""Single embedded DuckDB connection, guarded by a lock (DuckDB is single-writer)."""
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb

from app.core.config import settings

_lock = threading.RLock()
_con: duckdb.DuckDBPyConnection | None = None


def init_db() -> None:
    global _con
    path = settings.resolve(settings.duckdb_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings.resolve(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    _con = duckdb.connect(str(path))
    schema = (Path(__file__).parent / "schema.sql").read_text().replace(
        "__DIM__", str(settings.embedding_dim)
    )
    _con.execute(schema)
    try:
        _con.execute("INSTALL fts; LOAD fts;")
    except Exception:  # offline first run: keyword search degrades to vector only
        pass


@contextmanager
def db():
    with _lock:
        assert _con is not None, "database not initialised"
        yield _con
