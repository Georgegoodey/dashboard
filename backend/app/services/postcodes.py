"""postcodes.io (free, no key): borough and area codes for properties, and geocoding for commute points."""
import asyncio
from typing import Any

import httpx

from app.core.errors import InvalidInput
from app.db.database import Database
from app.pipeline.normalise import normalise_postcode
from app.repositories import geo

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


async def enrich_pending(db: Database, client: httpx.AsyncClient, limit: int = 500) -> dict[str, int]:
    """Fill borough for properties that lack it. Uses the cache first, then one bulk call per 100 new postcodes."""
    postcodes = await asyncio.to_thread(geo.postcodes_missing_borough, db, limit)
    if not postcodes:
        return {"postcodes": 0, "looked_up": 0, "properties_updated": 0}
    cached = await asyncio.to_thread(geo.cached_postcodes, db, postcodes)
    missing = [p for p in postcodes if p not in cached]
    found = await lookup_postcodes(client, missing) if missing else {}
    await asyncio.to_thread(geo.save_postcode_geo, db, found)
    updated = await asyncio.to_thread(geo.fill_boroughs, db)
    return {"postcodes": len(postcodes), "looked_up": len(found), "properties_updated": updated}


async def geocode(client: httpx.AsyncClient, postcode: str) -> dict | None:
    """postcodes.io record for one postcode (lat, lon, borough, ...), or None if invalid or unknown."""
    pc = normalise_postcode(postcode)
    if not pc:
        return None
    r = await client.get(f"{POSTCODES_IO}/postcodes/{pc.replace(' ', '%20')}")
    if r.status_code != 200:
        return None
    result: dict[str, Any] | None = r.json().get("result")
    return result


async def locate(client: httpx.AsyncClient, postcode: str) -> dict:
    """Geocode a full UK postcode for a commute point: normalised postcode, lat, lon and borough."""
    pc = normalise_postcode(postcode)
    if not pc:
        raise InvalidInput(f"'{postcode}' is not a full UK postcode, e.g. SW11 7FD")
    geo_result = await geocode(client, pc)
    if not geo_result or geo_result.get("latitude") is None:
        raise InvalidInput(f"postcodes.io does not know {pc}")
    return {"postcode": pc, "lat": geo_result["latitude"], "lon": geo_result["longitude"],
            "borough": geo_result.get("admin_district")}
