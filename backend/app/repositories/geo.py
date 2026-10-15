"""Postcode lookups cached in postcode_geo, and the borough fill for properties."""
from typing import Any

from app.db.database import Database


def postcodes_missing_borough(db: Database, limit: int) -> list[str]:
    rows = db.fetch_all(
        "SELECT DISTINCT postcode FROM properties WHERE borough IS NULL AND postcode IS NOT NULL LIMIT %s", (limit,))
    return [r["postcode"] for r in rows]


def cached_postcodes(db: Database, postcodes: list[str]) -> set[str]:
    rows = db.fetch_all("SELECT postcode FROM postcode_geo WHERE postcode = ANY(%s)", (postcodes,))
    return {r["postcode"] for r in rows}


def save_postcode_geo(db: Database, rows: dict[str, dict[str, Any]]) -> None:
    if not rows:
        return
    with db.conn() as c, c.cursor() as cur:
        for pc, r in rows.items():
            cur.execute(
                "INSERT INTO postcode_geo (postcode, lat, lon, borough, lsoa, msoa, region) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (postcode) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon, borough = EXCLUDED.borough, "
                "lsoa = EXCLUDED.lsoa, msoa = EXCLUDED.msoa, region = EXCLUDED.region, fetched_at = now()",
                (pc, r.get("latitude"), r.get("longitude"), r.get("admin_district"), r.get("lsoa"), r.get("msoa"),
                 r.get("region")))


def fill_boroughs(db: Database) -> int:
    return db.execute(
        "UPDATE properties p SET borough = g.borough FROM postcode_geo g "
        "WHERE g.postcode = p.postcode AND p.borough IS NULL AND g.borough IS NOT NULL")
