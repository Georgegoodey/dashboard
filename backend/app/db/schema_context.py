"""The text the SQL agent reads: the curated views with their column comments, value lists, ranges and sample rows.

Built from the database itself, so it never drifts from the schema. Cached briefly because it is rebuilt per chat request.
"""
import time
from decimal import Decimal

from psycopg.rows import tuple_row

from app.db import pg

_CACHE: dict = {"at": 0.0, "text": ""}
TTL_SECONDS = 120
MAX_DISTINCT = 15
NUMERIC = {"int2", "int4", "int8", "numeric", "float4", "float8"}


def _fmt(v) -> str:
    if isinstance(v, Decimal):
        v = float(v)
    return str(v)


def build() -> str:
    lines: list[str] = []
    with pg.ro_conn() as c:
        views = [r[0] for r in c.cursor(row_factory=tuple_row).execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema = 'public' ORDER BY 1").fetchall()]
        for v in views:
            comment = c.cursor(row_factory=tuple_row).execute(
                "SELECT obj_description(%s::regclass, 'pg_class')", (f"public.{v}",)).fetchone()[0]
            n = c.cursor(row_factory=tuple_row).execute(f'SELECT count(*) FROM "{v}"').fetchone()[0]
            lines.append(f'VIEW {v} ({n} rows)' + (f" - {comment}" if comment else ""))
            cols = c.cursor(row_factory=tuple_row).execute(
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod), t.typname, col_description(a.attrelid, a.attnum) "
                "FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid "
                "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
                (f"public.{v}",)).fetchall()
            for name, ftype, typname, doc in cols:
                note = ""
                if n and typname in ("text", "varchar", "bpchar") and name not in ("url", "description", "headline", "address", "key_features"):
                    vals = [r[0] for r in c.cursor(row_factory=tuple_row).execute(
                        f'SELECT "{name}" FROM "{v}" WHERE "{name}" IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT {MAX_DISTINCT + 1}'
                    ).fetchall()]
                    if 0 < len(vals) <= MAX_DISTINCT:
                        note = " values: " + ", ".join(sorted(map(str, vals)))
                elif n and typname in NUMERIC:
                    lo, hi = c.cursor(row_factory=tuple_row).execute(f'SELECT min("{name}"), max("{name}") FROM "{v}"').fetchone()
                    if lo is not None:
                        note = f" range: {_fmt(lo)} .. {_fmt(hi)}"
                lines.append(f'  - {name} {ftype}' + (f" -- {doc}" if doc else "") + note)
            if n:
                sample = c.cursor(row_factory=tuple_row).execute(f'SELECT * FROM "{v}" LIMIT 2').fetchall()
                lines.append("  sample rows: " + "; ".join(str(tuple(_fmt(x)[:60] if x is not None else None for x in r)) for r in sample))
            lines.append("")
        c.rollback()
    return "\n".join(lines).strip() or "(no views available)"


def schema_context() -> str:
    now = time.monotonic()
    if not _CACHE["text"] or now - _CACHE["at"] > TTL_SECONDS:
        try:
            _CACHE["text"] = build()
            _CACHE["at"] = now
        except Exception as e:  # noqa: BLE001
            return f"(database unavailable: {type(e).__name__}: {e})"
    return _CACHE["text"]
