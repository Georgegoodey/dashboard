import json
from contextvars import ContextVar

from langchain_core.tools import tool

from app.db import schema_context, sqlguard


@tool
def get_schema() -> str:
    """Describe the available views: columns with meanings and units, value lists, ranges and sample rows."""
    return schema_context.schema_context()


LLM_ROWS = 25
MAX_SQL_ERRORS = 2  # a failing query may be retried twice; after that the model must answer without it
# Holds a mutable counter so tool calls running in worker threads still update the request's count.
_sql_errors: ContextVar[list[int]] = ContextVar("sql_errors", default=[0])


def reset_sql_errors() -> None:
    _sql_errors.set([0])


@tool
def query_sql(sql: str) -> str:
    """Run ONE read-only PostgreSQL SELECT (CTEs and window functions are fine) against the views.
    Returns the columns and the first 25 rows as JSON (the user sees the full result separately).
    On error, read the message, fix the query and retry."""
    errors = _sql_errors.get()
    if errors[0] >= MAX_SQL_ERRORS:
        return "SQL failed repeatedly. Stop retrying: tell the user what you tried and that the query could not be run."
    try:
        res = sqlguard.run_readonly(sql)
        shown = res["rows"][:LLM_ROWS]          # keep the model's context small; the UI re-runs the SQL for the full result
        return json.dumps({"columns": res["columns"], "rows": shown, "total_rows": len(res["rows"]),
                           "shown": len(shown), "truncated": res["truncated"]}, default=str)
    except Exception as e:
        errors[0] += 1
        return f"SQL error: {e}"


TOOLS = [get_schema, query_sql]
