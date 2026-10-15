"""Read-only SQL for the console, the charts and the chat agent.

Defence in depth: a keyword guard here, then Postgres itself: the generated SQL runs as the `lettings_ro` role, which can
only SELECT from the curated views, in a read-only transaction, with a statement timeout (all set in migration 002).
"""
import re
from decimal import Decimal

from psycopg.rows import tuple_row

_ALLOWED = re.compile(r"^\s*(select|with|explain)\b", re.I)
_DENIED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set|reset|listen|notify|vacuum|"
    r"pg_\w+|lo_\w+|dblink\w*)\b",
    re.I,
)
MAX_ROWS = 500


def validate(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only a single statement is allowed")
    if not _ALLOWED.match(sql) or _DENIED.search(sql):
        raise ValueError("Only read-only SELECT queries on the curated views are allowed")
    return sql


def _json(v):
    if isinstance(v, Decimal):
        return float(v)  # numeric aggregates must reach the charts as numbers, not strings
    return v if isinstance(v, (int, float, str, bool, type(None))) else str(v)


def run_readonly(sql: str) -> dict:
    from app.db import pg

    sql = validate(sql)
    with pg.ro_conn() as c:
        with c.cursor(row_factory=tuple_row) as cur:
            cur.execute(sql)
            desc = cur.description or []
            cols = [d.name for d in desc]
            types = []
            for d in desc:
                t = c.adapters.types.get(d.type_code)
                types.append(t.name if t else str(d.type_code))
            rows = cur.fetchmany(MAX_ROWS + 1)
        c.rollback()           # read-only: never leave a transaction open on a pooled connection
    truncated = len(rows) > MAX_ROWS
    return {
        "columns": cols,
        "types": types,
        "rows": [[_json(v) for v in r] for r in rows[:MAX_ROWS]],
        "truncated": truncated,
    }
