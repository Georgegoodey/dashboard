"""Load tabular files into DuckDB and describe them for the SQL agent (schema-aware text-to-SQL)."""
import re
from pathlib import Path

from app.db.database import db

APP_TABLES = {"documents", "chunks", "messages"}


def safe_name(name: str) -> str:
    n = re.sub(r"\W+", "_", Path(name).stem.lower()).strip("_") or "data"
    return f"t_{n}" if n[0].isdigit() or n in APP_TABLES else n


def load_file(path: Path, table: str | None = None) -> dict:
    """Create (or replace) a table from a CSV/Parquet/JSON file."""
    table = safe_name(table or path.name)
    ext = path.suffix.lower()
    reader = {".csv": "read_csv_auto", ".parquet": "read_parquet",
              ".json": "read_json_auto"}.get(ext)
    if not reader:
        raise ValueError(f"Unsupported dataset type: {ext}")
    with db() as con:
        con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM {reader}(?)', [str(path)])
        n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    return {"table": table, "rows": n}


def user_tables() -> list[str]:
    with db() as con:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY 1"
        ).fetchall()
    return [r[0] for r in rows if r[0] not in APP_TABLES]


def list_datasets() -> list[dict]:
    out = []
    with db() as con:
        for t in user_tables():
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name=? ORDER BY ordinal_position", [t]).fetchall()
            n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            out.append({"table": t, "rows": n, "columns": [{"name": c, "type": d} for c, d in cols]})
    return out


def schema_context(max_distinct: int = 15) -> str:
    """Compact schema description: columns, types, categorical values, numeric ranges, sample rows."""
    lines: list[str] = []
    with db() as con:
        for t in user_tables():
            n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            lines.append(f'TABLE "{t}" ({n} rows)')
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name=? ORDER BY ordinal_position", [t]).fetchall()
            for c, d in cols:
                note = ""
                if d == "VARCHAR":
                    vals = [r[0] for r in con.execute(
                        f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT {max_distinct + 1}'
                    ).fetchall()]
                    if len(vals) <= max_distinct:
                        note = " values: " + ", ".join(map(str, sorted(vals)))
                elif d in ("DATE", "TIMESTAMP") or any(k in d for k in ("INT", "DOUBLE", "DECIMAL", "FLOAT")):
                    lo, hi = con.execute(f'SELECT min("{c}"), max("{c}") FROM "{t}"').fetchone()
                    note = f" range: {lo} .. {hi}"
                lines.append(f'  - "{c}" {d}{note}')
            sample = con.execute(f'SELECT * FROM "{t}" LIMIT 3').fetchall()
            lines.append("  sample rows: " + "; ".join(str(r) for r in sample))
    return "\n".join(lines) if lines else "(no datasets loaded yet)"
