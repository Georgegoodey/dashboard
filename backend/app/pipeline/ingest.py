"""Write listings to Postgres: upsert, price history, property matching, and withdrawn detection.

Synchronous (psycopg); async jobs call these through asyncio.to_thread.
"""
import hashlib
import json
from decimal import Decimal
from typing import Iterable

from psycopg import Cursor

from app.db import pg
from app.pipeline.normalise import normalise_address, normalise_postcode
from app.sources.base import RawListing

WITHDRAW_AFTER_MISSED_SCRAPES = 3


def _source_id(cur: Cursor, name: str) -> int:
    row = cur.execute("SELECT id FROM sources WHERE name = %s", (name,)).fetchone()
    if not row:
        raise ValueError(f"unknown source {name!r}")
    return row["id"]


def known_listings(source: str, ids: Iterable[str]) -> dict[str, dict]:
    """source_listing_id -> {id, rent_pcm, status} for listings we already have."""
    ids = list(ids)
    if not ids:
        return {}
    rows = pg.fetch_all(
        "SELECT l.source_listing_id, l.id, l.rent_pcm, l.status FROM listings l "
        "JOIN sources s ON s.id = l.source_id WHERE s.name = %s AND l.source_listing_id = ANY(%s)",
        (source, ids),
    )
    return {r["source_listing_id"]: r for r in rows}


def touch_known(source: str, items: list[RawListing]) -> dict[str, int]:
    """Refresh last_seen for listings already stored and record any rent change. Returns counts."""
    existing = known_listings(source, [i.source_listing_id for i in items])
    touched = repriced = revived = 0
    with pg.conn() as c, c.cursor() as cur:
        for item in items:
            row = existing.get(item.source_listing_id)
            if not row:
                continue
            touched += 1
            if row["status"] != "active":
                revived += 1
            cur.execute(
                "UPDATE listings SET last_seen = now(), missed_scrapes = 0, status = 'active' WHERE id = %s", (row["id"],))
            if item.rent_pcm is not None and row["rent_pcm"] is not None and Decimal(row["rent_pcm"]) != item.rent_pcm:
                repriced += 1
                cur.execute("UPDATE listings SET rent_pcm = %s, rent_pw = %s WHERE id = %s",
                            (item.rent_pcm, item.rent_pw, row["id"]))
                cur.execute("INSERT INTO listing_price_history (listing_id, rent_pcm, status) VALUES (%s, %s, 'active')",
                            (row["id"], item.rent_pcm))
        cur.execute("UPDATE properties SET last_seen = now() WHERE id IN "
                    "(SELECT property_id FROM listings WHERE source_listing_id = ANY(%s))",
                    ([i.source_listing_id for i in items],))
    return {"touched": touched, "repriced": repriced, "revived": revived}


def _find_or_create_property(cur: Cursor, raw: RawListing, source_id: int) -> int:
    """Match to an existing property, else create one.

    Two adverts from the SAME portal are never merged: a development such as 'The Lark, Moat Street' has many
    different flats with identical addresses. Cross-portal matching is exact on postcode, normalised address and
    bedrooms (the fuzzy pass and the possible-duplicate queue come with the second portal).
    """
    postcode = normalise_postcode(raw.postcode)
    addr_norm = normalise_address(raw.address)
    if postcode and addr_norm:
        row = cur.execute(
            "SELECT p.id FROM properties p WHERE p.postcode = %s AND p.address_norm = %s "
            "AND p.bedrooms IS NOT DISTINCT FROM %s "
            "AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.source_id = %s) "
            "ORDER BY p.id LIMIT 1",
            (postcode, addr_norm, raw.bedrooms, source_id),
        ).fetchone()
        if row:
            return row["id"]
    geom = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography" if raw.lat is not None and raw.lon is not None else "NULL"
    params: list = [raw.address, addr_norm, postcode, raw.outcode, raw.bedrooms, raw.bathrooms, raw.property_type]
    if geom != "NULL":
        params = [raw.address, addr_norm, postcode, raw.outcode, raw.bedrooms, raw.bathrooms, raw.property_type, raw.lon, raw.lat]
    sql = (f"INSERT INTO properties (address, address_norm, postcode, outcode, bedrooms, bathrooms, property_type, geom) "
           f"VALUES (%s, %s, %s, %s, %s, %s, %s, {geom}) RETURNING id")
    return cur.execute(sql, params).fetchone()["id"]


def _content_hash(raw: RawListing) -> str:
    key = [str(raw.rent_pcm), str(raw.available_from), raw.furnished, raw.description, raw.bedrooms]
    return hashlib.sha1(json.dumps(key, default=str).encode()).hexdigest()


def insert_new(raw: RawListing) -> tuple[int, int]:
    """Insert a listing we have not seen, with its property and first price-history row. Returns (listing_id, property_id)."""
    with pg.conn() as c, c.cursor() as cur:
        source_id = _source_id(cur, raw.source)
        property_id = _find_or_create_property(cur, raw, source_id)
        row = cur.execute(
            "INSERT INTO listings (property_id, source_id, source_listing_id, url, rent_pcm, rent_pw, deposit, furnished, "
            "let_type, min_term_months, available_from, agent_name, headline, description, key_features, raw, content_hash, "
            "detail_fetched_at, first_seen) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "CASE WHEN %s THEN now() END, coalesce(%s, now())) "
            "ON CONFLICT (source_id, source_listing_id) DO UPDATE SET last_seen = now(), status = 'active', missed_scrapes = 0 "
            "RETURNING id",
            (property_id, source_id, raw.source_listing_id, raw.url, raw.rent_pcm, raw.rent_pw, raw.deposit, raw.furnished,
             raw.let_type, raw.min_term_months, raw.available_from, raw.agent_name, raw.headline, raw.description,
             json.dumps(raw.key_features), json.dumps(raw.raw, default=str), _content_hash(raw), raw.has_detail, raw.first_listed),
        ).fetchone()
        cur.execute("INSERT INTO listing_price_history (listing_id, rent_pcm, status) VALUES (%s, %s, 'active')",
                    (row["id"], raw.rent_pcm))
        return row["id"], property_id


def mark_missing(source: str, outcode: str, seen_ids: set[str]) -> int:
    """After a COMPLETE scrape of an area: count a miss for active listings not seen, and withdraw after repeated misses."""
    with pg.conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE listings l SET missed_scrapes = missed_scrapes + 1 "
            "FROM properties p, sources s WHERE p.id = l.property_id AND s.id = l.source_id AND s.name = %s "
            "AND p.outcode = %s AND l.status = 'active' AND NOT (l.source_listing_id = ANY(%s))",
            (source, outcode, list(seen_ids)),
        )
        cur.execute(
            "UPDATE listings l SET status = 'withdrawn' FROM properties p, sources s "
            "WHERE p.id = l.property_id AND s.id = l.source_id AND s.name = %s AND p.outcode = %s "
            "AND l.status = 'active' AND l.missed_scrapes >= %s",
            (source, outcode, WITHDRAW_AFTER_MISSED_SCRAPES),
        )
        withdrawn = cur.rowcount
        if withdrawn:
            cur.execute(
                "INSERT INTO listing_price_history (listing_id, rent_pcm, status) "
                "SELECT l.id, l.rent_pcm, 'withdrawn' FROM listings l JOIN properties p ON p.id = l.property_id "
                "JOIN sources s ON s.id = l.source_id WHERE s.name = %s AND p.outcode = %s AND l.status = 'withdrawn' "
                "AND NOT EXISTS (SELECT 1 FROM listing_price_history h WHERE h.listing_id = l.id AND h.status = 'withdrawn')",
                (source, outcode),
            )
        return withdrawn


def pending_details(source: str, limit: int) -> list[dict]:
    """Listings whose detail page has not been fetched yet, newest first."""
    return pg.fetch_all(
        "SELECT l.id, l.source_listing_id, l.url, p.address, p.outcode FROM listings l "
        "JOIN sources s ON s.id = l.source_id JOIN properties p ON p.id = l.property_id "
        "WHERE s.name = %s AND l.detail_fetched_at IS NULL AND l.status = 'active' "
        "ORDER BY l.first_seen DESC LIMIT %s",
        (source, limit),
    )


def count_pending_details(source: str) -> int:
    row = pg.fetch_one(
        "SELECT count(*) AS n FROM listings l JOIN sources s ON s.id = l.source_id "
        "WHERE s.name = %s AND l.detail_fetched_at IS NULL AND l.status = 'active'", (source,))
    return row["n"] if row else 0


def save_detail(listing_id: int, raw: RawListing) -> None:
    """Store what the detail page revealed on the listing, and sharpen the property (exact postcode and coordinates)."""
    postcode = normalise_postcode(raw.postcode)
    with pg.conn() as c, c.cursor() as cur:
        row = cur.execute(
            "UPDATE listings SET deposit = %s, furnished = %s, let_type = %s, min_term_months = %s, "
            "available_from = coalesce(%s, available_from), agent_name = coalesce(%s, agent_name), "
            "headline = coalesce(%s, headline), description = coalesce(%s, description), key_features = %s, "
            "content_hash = %s, detail_fetched_at = now() WHERE id = %s RETURNING property_id",
            (raw.deposit, raw.furnished, raw.let_type, raw.min_term_months, raw.available_from, raw.agent_name,
             raw.headline, raw.description, json.dumps(raw.key_features), _content_hash(raw), listing_id),
        ).fetchone()
        if not row:
            return
        sets = ["address = coalesce(%s, address)", "address_norm = %s", "postcode = coalesce(%s, postcode)",
                "outcode = coalesce(%s, outcode)", "bedrooms = coalesce(%s, bedrooms)", "bathrooms = coalesce(%s, bathrooms)",
                "property_type = coalesce(%s, property_type)", "last_seen = now()"]
        params: list = [raw.address or None, normalise_address(raw.address), postcode, raw.outcode, raw.bedrooms,
                        raw.bathrooms, raw.property_type]
        if raw.lat is not None and raw.lon is not None:
            sets.append("geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography")
            params += [raw.lon, raw.lat]
        params.append(row["property_id"])
        cur.execute(f"UPDATE properties SET {', '.join(sets)} WHERE id = %s", params)
