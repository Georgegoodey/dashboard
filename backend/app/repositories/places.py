"""Home and work."""
from app.db.database import Database, Row


def list_all(db: Database) -> list[Row]:
    return db.fetch_all(
        "SELECT kind, label, address, postcode, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
        "FROM places ORDER BY kind")


def save(db: Database, kind: str, label: str, address: str | None, postcode: str, lat: float, lon: float) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO places (kind, label, address, postcode, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) "
            "ON CONFLICT (kind) DO UPDATE SET label = EXCLUDED.label, address = EXCLUDED.address, "
            "postcode = EXCLUDED.postcode, geom = EXCLUDED.geom, updated_at = now()",
            (kind, label, address, postcode, lon, lat))
        # routes to the old place are now wrong
        c.execute("DELETE FROM commute_routes WHERE profile_id IN (SELECT id FROM commute_profiles WHERE place_kind = %s)",
                  (kind,))


def delete(db: Database, kind: str) -> None:
    with db.conn() as c:
        c.execute("DELETE FROM commute_routes WHERE profile_id IN (SELECT id FROM commute_profiles WHERE place_kind = %s)",
                  (kind,))
        c.execute("DELETE FROM places WHERE kind = %s", (kind,))
