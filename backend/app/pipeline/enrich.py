"""Enrich properties with borough and area codes from postcodes.io (free, no key). Results are cached in postcode_geo."""
import asyncio

import httpx

from app.db import pg
from app.pipeline.normalise import normalise_postcode

POSTCODES_IO = "https://api.postcodes.io"
BULK_LIMIT = 100  # postcodes.io accepts up to 100 per bulk request


async def lookup_postcodes(client: httpx.AsyncClient, postcodes: list[str]) -> dict[str, dict]:
    """Bulk lookup. Returns normalised postcode -> postcodes.io result for those it knows."""
    found: dict[str, dict] = {}
    for i in range(0, len(postcodes), BULK_LIMIT):
        chunk = postcodes[i:i + BULK_LIMIT]
        r = await client.post(f"{POSTCODES_IO}/postcodes", json={"postcodes": chunk})
        r.raise_for_status()
        for item in r.json().get("result") or []:
            res = item.get("result")
            if res:
                found[normalise_postcode(item["query"]) or item["query"]] = res
    return found


def _save_postcode_geo(rows: dict[str, dict]) -> None:
    if not rows:
        return
    with pg.conn() as c, c.cursor() as cur:
        for pc, r in rows.items():
            cur.execute(
                "INSERT INTO postcode_geo (postcode, lat, lon, borough, lsoa, msoa, region) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (postcode) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon, borough = EXCLUDED.borough, "
                "lsoa = EXCLUDED.lsoa, msoa = EXCLUDED.msoa, region = EXCLUDED.region, fetched_at = now()",
                (pc, r.get("latitude"), r.get("longitude"), r.get("admin_district"), r.get("lsoa"), r.get("msoa"), r.get("region")),
            )


async def enrich_pending(client: httpx.AsyncClient, limit: int = 500) -> dict[str, int]:
    """Fill borough for properties that lack it. Uses the cache first, then one bulk call per 100 new postcodes."""
    rows = await asyncio.to_thread(
        pg.fetch_all,
        "SELECT DISTINCT postcode FROM properties WHERE borough IS NULL AND postcode IS NOT NULL LIMIT %s", (limit,))
    postcodes = [r["postcode"] for r in rows]
    if not postcodes:
        return {"postcodes": 0, "looked_up": 0, "properties_updated": 0}

    cached = {r["postcode"] for r in await asyncio.to_thread(
        pg.fetch_all, "SELECT postcode FROM postcode_geo WHERE postcode = ANY(%s)", (postcodes,))}
    missing = [p for p in postcodes if p not in cached]
    found = await lookup_postcodes(client, missing) if missing else {}
    await asyncio.to_thread(_save_postcode_geo, found)

    updated = await asyncio.to_thread(
        pg.execute,
        "UPDATE properties p SET borough = g.borough FROM postcode_geo g "
        "WHERE g.postcode = p.postcode AND p.borough IS NULL AND g.borough IS NOT NULL")
    return {"postcodes": len(postcodes), "looked_up": len(found), "properties_updated": updated}


async def geocode(client: httpx.AsyncClient, postcode: str) -> dict | None:
    """postcodes.io record for one postcode (lat, lon, borough, ...), or None if invalid or unknown."""
    pc = normalise_postcode(postcode)
    if not pc:
        return None
    r = await client.get(f"{POSTCODES_IO}/postcodes/{pc.replace(' ', '%20')}")
    if r.status_code != 200:
        return None
    return r.json().get("result")
