"""Search areas (postcode outcodes) to scrape."""
from app.db.database import Database, Row


def list_all(db: Database) -> list[Row]:
    return db.fetch_all(
        "SELECT a.id, a.label, a.outcode, a.enabled, "
        "(SELECT count(*) FROM properties p WHERE p.outcode = a.outcode) AS properties "
        "FROM search_areas a ORDER BY a.outcode")


def list_enabled(db: Database, source: str | None = None) -> list[Row]:
    """Enabled areas. With a `source`, the ones scraped longest ago (or never) on that portal come first."""
    if source is None:
        return db.fetch_all("SELECT id, label, outcode, source_ids FROM search_areas WHERE enabled ORDER BY outcode")
    return db.fetch_all(
        "SELECT id, label, outcode, source_ids FROM search_areas WHERE enabled "
        "ORDER BY (scraped_at ->> %s)::timestamptz NULLS FIRST, outcode", (source,))


def mark_scraped(db: Database, area_id: int, source: str) -> None:
    """Record that a portal's search of this area finished."""
    db.execute("UPDATE search_areas SET scraped_at = scraped_at || jsonb_build_object(%s::text, to_char(now() AT TIME ZONE 'UTC', "
               "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) WHERE id = %s", (source, area_id))


def upsert(db: Database, outcode: str, label: str, enabled: bool) -> int:
    row = db.fetch_one(
        "INSERT INTO search_areas (label, outcode, enabled) VALUES (%s, %s, %s) "
        "ON CONFLICT (outcode) DO UPDATE SET label = EXCLUDED.label, enabled = EXCLUDED.enabled RETURNING id",
        (label, outcode, enabled))
    assert row is not None
    return int(row["id"])


def update(db: Database, area_id: int, label: str | None, enabled: bool) -> bool:
    return bool(db.execute("UPDATE search_areas SET label = coalesce(%s, label), enabled = %s WHERE id = %s",
                           (label, enabled, area_id)))


def delete(db: Database, area_id: int) -> None:
    db.execute("DELETE FROM search_areas WHERE id = %s", (area_id,))


def save_source_id(db: Database, area_id: int, source: str, location_id: str) -> None:
    """Cache a portal's location id for an area, so it is looked up once."""
    db.execute("UPDATE search_areas SET source_ids = source_ids || jsonb_build_object(%s::text, %s::text) WHERE id = %s",
               (source, location_id, area_id))
