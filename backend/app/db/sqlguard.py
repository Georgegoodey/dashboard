"""Read-only SQL for the console, the charts and the chat agent.

Two layers. This module parses the statement (sqlglot, PostgreSQL dialect) and accepts only one SELECT that reads the
curated views and calls no dangerous function. Postgres then enforces the real boundary: generated SQL runs as the
`lettings_ro` role, which can only SELECT from those views, in a read-only transaction with a statement timeout.
"""
from decimal import Decimal
from typing import Any

import sqlglot
from psycopg.rows import tuple_row
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.db.database import Database

ALLOWED_RELATIONS = frozenset({"v_properties", "v_commutes", "v_commute_points", "v_price_changes", "v_property_text", "v_job_runs"})
DENIED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
DENIED_FUNCTIONS = frozenset({"set_config", "current_setting", "query_to_xml", "query_to_xml_and_xmlschema",
                              "table_to_xml", "cursor_to_xml", "database_to_xml", "version"})
# nodes that are never part of a plain read
_FORBIDDEN_NODES = (exp.Command, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Merge,
                    exp.Into, exp.Lock, exp.Set, exp.Use, exp.Copy, exp.TruncateTable, exp.Grant)
MAX_ROWS = 500


class SqlRejected(ValueError):
    """The statement is not an allowed read-only query."""


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return str(node.sql_name()).lower()


def validate(sql: str) -> str:
    """Return the cleaned statement, or raise SqlRejected with a message the model can act on."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        raise SqlRejected(f"Could not parse the SQL as PostgreSQL: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise SqlRejected("Only a single statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query) or isinstance(stmt, exp.Subquery):
        raise SqlRejected("Only SELECT queries are allowed")

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlRejected("Only read-only SELECT queries on the curated views are allowed")

    cte_names = {str(cte.alias).lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if isinstance(table.this, exp.Func):          # a table function such as generate_series(): checked below
            continue
        name = table.name.lower()
        schema_ok = not table.db or table.db.lower() == "public"
        if name in cte_names and not table.db:
            continue
        if not schema_ok or table.catalog or name not in ALLOWED_RELATIONS:
            allowed = ", ".join(sorted(ALLOWED_RELATIONS))
            raise SqlRejected(f"Relation '{table.sql()}' is not available. Use only these views: {allowed}")

    for fn in stmt.find_all(exp.Func):
        name = _function_name(fn)
        if name in DENIED_FUNCTIONS or name.startswith(DENIED_FUNCTION_PREFIXES):
            raise SqlRejected(f"Function {name}() is not allowed")
    return stmt.sql(dialect="postgres")


def _json(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)  # numeric aggregates must reach the charts as numbers, not strings
    return v if isinstance(v, (int, float, str, bool, type(None))) else str(v)


def run_readonly(db: Database, sql: str) -> dict[str, Any]:
    """Validate and run `sql` as the read-only role. Returns columns, Postgres type names, rows and a truncation flag."""
    safe = validate(sql)
    with db.ro_conn() as c:
        with c.cursor(row_factory=tuple_row) as cur:
            cur.execute(safe)
            desc = cur.description or []
            cols = [d.name for d in desc]
            types = []
            for d in desc:
                t = c.adapters.types.get(d.type_code)
                types.append(t.name if t else str(d.type_code))
            rows = cur.fetchmany(MAX_ROWS + 1)
        c.rollback()           # read-only: never leave a transaction open on a pooled connection
    return {
        "columns": cols,
        "types": types,
        "rows": [[_json(v) for v in r] for r in rows[:MAX_ROWS]],
        "truncated": len(rows) > MAX_ROWS,
    }
