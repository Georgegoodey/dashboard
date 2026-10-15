"""Reads over the curated views for the Properties panel, plus overall counts."""
from decimal import Decimal
from typing import Any

from app.db.database import Database, Row

# API sort key -> column of v_properties (a whitelist: never interpolate user input)
SORTS = {
    "rent": "rent_pcm", "commute": "work_am_min", "newest": "days_on_market", "bedrooms": "bedrooms",
    "vs_median": "rent_vs_median_pct", "distance_work": "distance_to_work_km",
}


def _where(*, q: str | None, min_rent: float | None, max_rent: float | None, min_beds: int | None, max_beds: int | None,
           borough: str | None, max_commute: int | None, furnished: str | None) -> tuple[str, list[Any]]:
    """The WHERE clause shared by the list and the map. Only constant fragments are joined; values are parameters."""
    where: list[str] = ["true"]
    params: list[Any] = []
    if q:
        where.append("(address ILIKE %s OR headline ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    for cond, val in (("rent_pcm >= %s", min_rent), ("rent_pcm <= %s", max_rent), ("bedrooms >= %s", min_beds),
                      ("bedrooms <= %s", max_beds), ("work_am_min <= %s", max_commute)):
        if val is not None:
            where.append(cond)
            params.append(val)
    if borough:
        where.append("borough ILIKE %s")
        params.append(borough)
    if furnished:
        where.append("furnished ILIKE %s")
        params.append(f"{furnished}%")
    return " AND ".join(where), params


def search(db: Database, *, sort: str, order: str, limit: int, offset: int, **filters: Any) -> dict[str, Any]:
    clause, params = _where(**filters)
    col = SORTS.get(sort, "days_on_market")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    total = db.fetch_one(f"SELECT count(*) AS n FROM v_properties WHERE {clause}", params)
    rows = db.fetch_all(
        f"SELECT * FROM v_properties WHERE {clause} ORDER BY {col} {direction} NULLS LAST, id LIMIT %s OFFSET %s",
        [*params, limit, offset])
    return {"total": total["n"] if total else 0, "rows": rows}


def map_points(db: Database, **filters: Any) -> dict[str, Any]:
    """Every matching property that has coordinates, with just the fields the map draws (no paging)."""
    clause, params = _where(**filters)
    rows = db.fetch_all(
        "SELECT id, lat, lon, address, url, rent_pcm, bedrooms, borough, work_am_min, work_pm_min, rent_vs_median_pct, days_on_market "
        f"FROM v_properties WHERE lat IS NOT NULL AND lon IS NOT NULL AND {clause} ORDER BY id", params)
    # numeric columns arrive as Decimal, which JSON would carry as strings; the map needs real numbers
    points = [{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in rows]
    return {"total": len(points), "points": points}


def detail(db: Database, property_id: int) -> dict[str, Any] | None:
    prop = db.fetch_one("SELECT * FROM v_properties WHERE id = %s", (property_id,))
    if not prop:
        return None
    listings = db.fetch_all(
        "SELECT s.name AS source, l.url, l.status, l.rent_pcm, l.deposit, l.furnished, l.let_type, l.min_term_months, "
        "l.available_from, l.agent_name, l.headline, l.description, l.key_features, l.first_seen, l.last_seen "
        "FROM listings l JOIN sources s ON s.id = l.source_id WHERE l.property_id = %s ORDER BY l.status, l.rent_pcm",
        (property_id,))
    history = db.fetch_all(
        "SELECT h.observed_at, h.rent_pcm, h.status FROM listing_price_history h JOIN listings l ON l.id = h.listing_id "
        "WHERE l.property_id = %s ORDER BY h.observed_at", (property_id,))
    routes = db.fetch_all(
        "SELECT DISTINCT ON (cp.slug) cp.slug, cp.label, r.ref_date, r.duration_min, r.walk_min, r.transfers, "
        "r.fare_pence, r.summary FROM commute_routes r JOIN commute_profiles cp ON cp.id = r.profile_id "
        "WHERE r.property_id = %s ORDER BY cp.slug, r.ref_date DESC", (property_id,))
    return {"property": prop, "listings": listings, "price_history": history, "commutes": routes}


def counts(db: Database) -> Row:
    row = db.fetch_one(
        "SELECT (SELECT count(*) FROM listings WHERE status = 'active') AS active_listings, "
        "(SELECT count(*) FROM properties p WHERE EXISTS "
        "(SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')) AS properties, "
        "(SELECT count(*) FROM listings WHERE status = 'active' AND detail_fetched_at IS NULL) AS detail_pending, "
        "(SELECT count(*) FROM search_areas WHERE enabled) AS areas, "
        "(SELECT count(*) FROM places) AS places")
    assert row is not None
    return row
