"""What is in the database (tables, views, columns): for the Database panel."""
from typing import Any

from app.db.database import Database

# exact row counts for tables (query_to_xml runs the count inside this one statement); views are not counted
_RELATIONS = """
SELECT c.relname AS name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view' ELSE 'materialized view' END AS kind,
       CASE WHEN c.relkind = 'r' THEN
         (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint
       END AS rows,
       CASE WHEN c.relkind IN ('r', 'm') THEN pg_size_pretty(pg_total_relation_size(c.oid)) END AS size
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm')
  AND c.relname NOT IN ('spatial_ref_sys', 'geometry_columns', 'geography_columns')  -- PostGIS internals
ORDER BY c.relkind, c.relname
"""

_COLUMNS = """
SELECT table_name, column_name, data_type, is_nullable = 'YES' AS nullable
FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position
"""


def overview(db: Database) -> dict[str, Any]:
    info = db.fetch_one(
        "SELECT current_database() AS name, current_user AS role, version() AS server_version, "
        "pg_size_pretty(pg_database_size(current_database())) AS size")
    assert info is not None
    relations = db.fetch_all(_RELATIONS)
    columns: dict[str, list[dict[str, Any]]] = {}
    for c in db.fetch_all(_COLUMNS):
        columns.setdefault(c["table_name"], []).append(
            {"name": c["column_name"], "type": c["data_type"], "nullable": c["nullable"]})
    return {**info, "relations": [{**r, "columns": columns.get(r["name"], [])} for r in relations]}
