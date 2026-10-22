"""Commute points (any number of places you travel to) and the journeys planned for each."""
from datetime import time
from typing import Any

from app.db.database import Database, Row

# one journey to the point (arrive by), and the way back (leave at); a point starts with one or both
TO_POINT = {"direction": "to_place", "anchor": "arrive_by", "local_time": time(9, 0), "weekday": 1}
FROM_POINT = {"direction": "from_place", "anchor": "depart_at", "local_time": time(18, 0), "weekday": 1}


def list_all(db: Database) -> list[dict[str, Any]]:
    """Every point (active or not) with its journeys, in the order they were added."""
    points = db.fetch_all(
        "SELECT id, label, address, postcode, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, enabled, position "
        "FROM commute_points ORDER BY position, id")
    journeys = db.fetch_all(
        "SELECT id, point_id, direction, anchor, local_time, weekday, enabled FROM commute_profiles ORDER BY id")
    by_point: dict[int, list[Row]] = {}
    for j in journeys:
        by_point.setdefault(j["point_id"], []).append(j)
    return [{**p, "journeys": by_point.get(p["id"], [])} for p in points]


def add(db: Database, label: str, address: str | None, postcode: str, lat: float, lon: float,
        journeys: list[dict[str, Any]]) -> int:
    with db.conn() as c:
        row = c.execute(
            "INSERT INTO commute_points (label, address, postcode, geom, position) "
            "VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, "
            "        (SELECT coalesce(max(position) + 1, 0) FROM commute_points)) RETURNING id",
            (label, address, postcode, lon, lat)).fetchone()
        assert row is not None
        for j in journeys:
            c.execute(
                "INSERT INTO commute_profiles (point_id, direction, anchor, local_time, weekday) VALUES (%s, %s, %s, %s, %s)",
                (row["id"], j["direction"], j["anchor"], j["local_time"], j["weekday"]))
    return int(row["id"])


def update(db: Database, point_id: int, label: str, address: str | None, enabled: bool,
           place: tuple[str, float, float] | None = None) -> bool:
    """Rename, switch on or off, or (with `place` = postcode, lat, lon) move a point. Moving drops its routes."""
    with db.conn() as c:
        if place:
            pc, lat, lon = place
            row = c.execute(
                "UPDATE commute_points SET label = %s, address = %s, enabled = %s, postcode = %s, "
                "geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, updated_at = now() WHERE id = %s RETURNING id",
                (label, address, enabled, pc, lon, lat, point_id)).fetchone()
            if row:
                c.execute("DELETE FROM commute_routes WHERE profile_id IN (SELECT id FROM commute_profiles WHERE point_id = %s)",
                          (point_id,))
        else:
            row = c.execute(
                "UPDATE commute_points SET label = %s, address = %s, enabled = %s, updated_at = now() WHERE id = %s RETURNING id",
                (label, address, enabled, point_id)).fetchone()
    return row is not None


def delete(db: Database, point_id: int) -> bool:
    """Remove a point for good; its journeys and routes go with it (switching it off keeps them)."""
    with db.conn() as c:
        return c.execute("DELETE FROM commute_points WHERE id = %s RETURNING id", (point_id,)).fetchone() is not None


def add_journey(db: Database, point_id: int, direction: str, anchor: str, local_time: time, weekday: int) -> int | None:
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM commute_points WHERE id = %s", (point_id,)).fetchone():
            return None
        row = c.execute(
            "INSERT INTO commute_profiles (point_id, direction, anchor, local_time, weekday) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id", (point_id, direction, anchor, local_time, weekday)).fetchone()
    assert row is not None
    return int(row["id"])


def update_journey(db: Database, journey_id: int, direction: str, anchor: str, local_time: time, weekday: int,
                   enabled: bool) -> bool:
    """Change a journey. Routes are dropped (and so planned again) only if its timing changed. False if the id is unknown."""
    with db.conn() as c:
        old = c.execute("SELECT direction, anchor, local_time, weekday FROM commute_profiles WHERE id = %s FOR UPDATE",
                        (journey_id,)).fetchone()
        if not old:
            return False
        c.execute("UPDATE commute_profiles SET direction = %s, anchor = %s, local_time = %s, weekday = %s, enabled = %s "
                  "WHERE id = %s", (direction, anchor, local_time, weekday, enabled, journey_id))
        if (old["direction"], old["anchor"], old["local_time"], old["weekday"]) != (direction, anchor, local_time, weekday):
            c.execute("DELETE FROM commute_routes WHERE profile_id = %s", (journey_id,))
    return True


def delete_journey(db: Database, journey_id: int) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM commute_profiles WHERE id = %s RETURNING id", (journey_id,)).fetchone() is not None
