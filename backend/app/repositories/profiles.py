"""Commute profiles: when each journey is planned."""
from datetime import time

from app.db.database import Database, Row


def list_all(db: Database) -> list[Row]:
    return db.fetch_all(
        "SELECT slug, label, place_kind, direction, anchor, local_time, weekday, enabled FROM commute_profiles ORDER BY id")


def update(db: Database, slug: str, local_time: time, weekday: int, enabled: bool) -> bool:
    """Change a profile and drop its routes so they are recomputed. False if the slug is unknown."""
    with db.conn() as c:
        row = c.execute(
            "UPDATE commute_profiles SET local_time = %s, weekday = %s, enabled = %s WHERE slug = %s RETURNING id",
            (local_time, weekday, enabled, slug)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM commute_routes WHERE profile_id = %s", (row["id"],))
    return True
