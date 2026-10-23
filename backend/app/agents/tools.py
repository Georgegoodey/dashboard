"""The agent's tools. They are built around a Database, so nothing here reaches for global state."""
import json
from contextvars import ContextVar

from langchain_core.tools import BaseTool, tool

from app.db import sqlguard
from app.db.database import Database
from app.rag.schema import SchemaContext
from app.rag.search import search_descriptions as run_search

LLM_ROWS = 25
MAX_SQL_ERRORS = 2  # a failing query may be retried twice; after that the model must answer without it
# The failed-query count for the chat request being answered. It is a one-item list so that tool calls running in worker
# threads, which get a copy of the context, still update the request's own count. There is no shared default: a counter is
# made for each request (reset_sql_errors, at the start of a chat) and, failing that, for each use.
_sql_errors: ContextVar[list[int] | None] = ContextVar("sql_errors", default=None)


def reset_sql_errors() -> list[int]:
    counter = [0]
    _sql_errors.set(counter)
    return counter


def _error_counter() -> list[int]:
    return _sql_errors.get() or reset_sql_errors()


def build_tools(db: Database, schema: SchemaContext) -> list[BaseTool]:
    @tool
    def get_schema() -> str:
        """Describe the available views: columns with meanings and units, value lists, ranges and sample rows."""
        return schema.text()

    @tool
    def query_sql(sql: str) -> str:
        """Run ONE read-only PostgreSQL SELECT (CTEs and window functions are fine) against the views.
        Returns the columns and the first 25 rows as JSON (the user sees the full result separately).
        On error, read the message, fix the query and retry."""
        errors = _error_counter()
        if errors[0] >= MAX_SQL_ERRORS:
            return "SQL failed repeatedly. Stop retrying: tell the user what you tried and that the query could not be run."
        try:
            res = sqlguard.run_readonly(db, sql)
            shown = res["rows"][:LLM_ROWS]          # keep the model's context small; the UI re-runs the SQL for the full result
            return json.dumps({"columns": res["columns"], "rows": shown, "total_rows": len(res["rows"]),
                               "shown": len(shown), "truncated": res["truncated"]}, default=str)
        except Exception as e:
            errors[0] += 1
            return f"SQL error: {e}"

    @tool
    def search_descriptions(query: str, limit: int = 10) -> str:
        """Full-text search of advert wording (descriptions and headlines), best matches first, with highlighted excerpts.
        Use it to FIND properties by what the advert says (e.g. 'garden', 'balcony', '"pets allowed"', 'quiet -ground').
        Words are ANDed; "double quotes" match a phrase; `or` alternates; `-word` excludes. Returns property ids you can
        then filter and rank with query_sql (v_properties.id)."""
        try:
            return json.dumps(run_search(db, query, limit), default=str)
        except Exception as e:
            return f"Search error: {e}"

    return [get_schema, query_sql, search_descriptions]
