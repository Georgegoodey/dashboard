"""The text the SQL agent reads: the curated views with their column comments, value lists, ranges and sample rows.

Built from the database itself, so it never drifts from the schema. Cached briefly because it is needed per chat request.
"""
import time
from decimal import Decimal
from typing import Any

from psycopg.rows import tuple_row

from app.db.database import Database

TTL_SECONDS = 120
MAX_DISTINCT = 15
NUMERIC = {"int2", "int4", "int8", "numeric", "float4", "float8"}
FREE_TEXT = {"url", "description", "headline", "address", "key_features"}   # long values: no value lists
HIDDEN_TYPES = {"tsvector"}                                              # search plumbing the model must not select


def _fmt(v: Any) -> str:
    if isinstance(v, Decimal):
        v = float(v)
    return str(v)


class SchemaContext:
    def __init__(self, db: Database, ttl_seconds: int = TTL_SECONDS) -> None:
        self._db = db
        self._ttl = ttl_seconds
        self._text = ""
        self._at = 0.0

    def text(self) -> str:
        now = time.monotonic()
        if not self._text or now - self._at > self._ttl:
            try:
                self._text = self.build()
                self._at = now
            except Exception as e:
                return f"(database unavailable: {type(e).__name__}: {e})"
        return self._text

    def build(self) -> str:
        lines: list[str] = []
        with self._db.ro_conn() as c:
            def q(sql: str, params: tuple[Any, ...] | None = None) -> Any:
                return c.cursor(row_factory=tuple_row).execute(sql, params)

            views = [r[0] for r in q("SELECT table_name FROM information_schema.views "
                                     "WHERE table_schema = 'public' ORDER BY 1").fetchall()]
            for v in views:
                comment = q("SELECT obj_description(%s::regclass, 'pg_class')", (f"public.{v}",)).fetchone()[0]
                n = q(f'SELECT count(*) FROM "{v}"').fetchone()[0]  # noqa: S608
                lines.append(f"VIEW {v} ({n} rows)" + (f" - {comment}" if comment else ""))
                cols = q(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), t.typname, col_description(a.attrelid, a.attnum) "
                    "FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid "
                    "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
                    (f"public.{v}",)).fetchall()
                shown: list[str] = []
                for name, ftype, typname, doc in cols:
                    if typname in HIDDEN_TYPES:
                        continue
                    shown.append(name)
                    note = ""
                    if n and typname in ("text", "varchar", "bpchar") and name not in FREE_TEXT:
                        vals = [r[0] for r in q(
                            f'SELECT "{name}" FROM "{v}" WHERE "{name}" IS NOT NULL GROUP BY 1 '  # noqa: S608
                            f"ORDER BY count(*) DESC LIMIT {MAX_DISTINCT + 1}").fetchall()]
                        if 0 < len(vals) <= MAX_DISTINCT:
                            note = " values: " + ", ".join(sorted(map(str, vals)))
                    elif n and typname in NUMERIC:
                        lo, hi = q(f'SELECT min("{name}"), max("{name}") FROM "{v}"').fetchone()  # noqa: S608
                        if lo is not None:
                            note = f" range: {_fmt(lo)} .. {_fmt(hi)}"
                    lines.append(f"  - {name} {ftype}" + (f" -- {doc}" if doc else "") + note)
                if n and shown:
                    select_list = ", ".join(f'"{name}"' for name in shown)
                    sample = q(f'SELECT {select_list} FROM "{v}" LIMIT 2').fetchall()  # noqa: S608
                    lines.append("  sample rows: " + "; ".join(
                        str(tuple(_fmt(x)[:60] if x is not None else None for x in r)) for r in sample))
                lines.append("")
            c.rollback()
        return "\n".join(lines).strip() or "(no views available)"
