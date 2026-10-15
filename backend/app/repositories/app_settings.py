"""Key/value settings stored as JSON (the search filters, with room for more)."""
import json
from typing import Any

from app.db.database import Database


def get(db: Database, key: str) -> dict[str, Any]:
    row = db.fetch_one("SELECT value FROM app_settings WHERE key = %s", (key,))
    value = row["value"] if row else {}
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value)


def put(db: Database, key: str, value: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, json.dumps(value)))
