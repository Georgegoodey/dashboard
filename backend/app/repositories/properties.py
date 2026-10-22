"""Reads over the curated views for the Properties panel, plus overall counts."""
from decimal import Decimal
from typing import Any

from app.core.errors import InvalidInput
from app.db.database import Database, Row

# API sort key -> column of v_properties (a whitelist: never interpolate user input)
SORTS = {
    "rent": "rent_pcm", "newest": "days_on_market", "bedrooms": "bedrooms", "vs_median": "rent_vs_median_pct",
}
# The longest of a point's journeys, so "30 minutes to Work" holds for the morning and the evening trip.
_POINT_WORST = "(SELECT max(c.duration_min) FROM v_commutes c WHERE c.property_id = v_properties.id AND c.point_id = %s)"
_ANY_POINT = "(SELECT min(c.duration_min) FROM v_commutes c WHERE c.property_id = v_properties.id)"


def parse_commute(db: Database, specs: list[str]) -> list[tuple[int, int]]:
    """Turn 'POINT:MINUTES' filters into (point id, minutes). POINT may be 'all', meaning every active point."""
    out: list[tuple[int, int]] = []
    for spec in specs:
        point, _, minutes = spec.partition(":")
        if not minutes.isdigit() or not (point == "all" or point.isdigit()):
            raise InvalidInput(f"'{spec}' is not a commute filter; use POINT_ID:MINUTES or all:MINUTES")
        if point == "all":
            out += [(r["point_id"], int(minutes)) for r in db.fetch_all("SELECT point_id FROM v_commute_points ORDER BY 1")]
        else:
            out.append((int(point), int(minutes)))
    return out


def _within(db: Database, commute: list[tuple[int, int]]) -> list[int] | None:
    """Ids of the properties inside every (point, minutes) limit, or None when there are no limits.

    Every journey of a point must be planned and within the limit; one not yet computed (or with no route) fails.
    Resolved here, apart from v_properties: as a subquery in its WHERE the planner re-runs the whole view per row.
    """
    ids: set[int] | None = None
    for point_id, minutes in commute:
        rows = db.fetch_all(
            "SELECT c.property_id FROM v_commutes c WHERE c.point_id = %s GROUP BY c.property_id "
            "HAVING max(c.duration_min) <= %s AND count(c.duration_min) = count(*) "
            "AND count(*) = (SELECT count(*) FROM commute_profiles WHERE point_id = %s AND enabled)",
            (point_id, minutes, point_id))
        found = {r["property_id"] for r in rows}
        ids = found if ids is None else ids & found
        if not ids:
            break
    return None if ids is None else sorted(ids)


def _where(*, q: str | None, min_rent: float | None, max_rent: float | None, min_beds: int | None, max_beds: int | None,
           borough: str | None, within: list[int] | None, furnished: str | None) -> tuple[str, list[Any]]:
    """The WHERE clause shared by the list and the map. Only constant fragments are joined; values are parameters."""
    where: list[str] = ["true"]
    params: list[Any] = []
    if q:
        where.append("(address ILIKE %s OR headline ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    for cond, val in (("rent_pcm >= %s", min_rent), ("rent_pcm <= %s", max_rent), ("bedrooms >= %s", min_beds),
                      ("bedrooms <= %s", max_beds)):
        if val is not None:
            where.append(cond)
            params.append(val)
    if borough:
        where.append("borough ILIKE %s")
        params.append(borough)
    if furnished:
        where.append("furnished ILIKE %s")
        params.append(f"{furnished}%")
    if within is not None:
        where.append("id = ANY(%s)")
        params.append(within)
    return " AND ".join(where), params


def search(db: Database, *, sort: str, order: str, limit: int, offset: int, commute: list[tuple[int, int]],
           **filters: Any) -> dict[str, Any]:
    clause, params = _where(within=_within(db, commute), **filters)
    sort_params: list[Any] = []
    if sort.startswith("commute:") and sort[8:].isdigit():
        col, sort_params = _POINT_WORST, [int(sort[8:])]
    elif sort == "commute":
        col = _ANY_POINT
    else:
        col = SORTS.get(sort, "days_on_market")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    total = db.fetch_one(f"SELECT count(*) AS n FROM v_properties WHERE {clause}", params)
    rows = db.fetch_all(
        f"SELECT * FROM v_properties WHERE {clause} ORDER BY {col} {direction} NULLS LAST, id LIMIT %s OFFSET %s",
        [*params, *sort_params, limit, offset])
    commutes = _commutes_for(db, [r["id"] for r in rows])
    return {"total": total["n"] if total else 0, "rows": [{**r, "commutes": commutes.get(r["id"], [])} for r in rows]}


def _commutes_for(db: Database, property_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """The computed journeys of these properties, grouped by property (active points and journeys only)."""
    if not property_ids:
        return {}
    rows = db.fetch_all(
        "SELECT property_id, point_id, profile_id, direction, anchor, local_time, duration_min, walk_min, transfers, "
        "fare_pence, distance_km FROM v_commutes WHERE property_id = ANY(%s) ORDER BY point_id, profile_id", (property_ids,))
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.pop("property_id"), []).append(
            {k: float(v) if isinstance(v, Decimal) else (v.strftime("%H:%M") if k == "local_time" else v) for k, v in r.items()})
    return out


def map_points(db: Database, *, commute: list[tuple[int, int]], **filters: Any) -> dict[str, Any]:
    """Every matching property that has coordinates, with just the fields the map draws (no paging)."""
    clause, params = _where(within=_within(db, commute), **filters)
    rows = db.fetch_all(
        "SELECT id, lat, lon, address, url, rent_pcm, bedrooms, borough, rent_vs_median_pct, days_on_market "
        f"FROM v_properties WHERE lat IS NOT NULL AND lon IS NOT NULL AND {clause} ORDER BY id", params)
    # numeric columns arrive as Decimal, which JSON would carry as strings; the map needs real numbers
    commutes = _commutes_for(db, [r["id"] for r in rows])
    points = [{**{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()}, "commutes": commutes.get(r["id"], [])}
              for r in rows]
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
        "SELECT point_id, point_label, profile_id, journey, direction, anchor, local_time, duration_min, walk_min, transfers, "
        "fare_pence, summary, distance_km FROM v_commutes WHERE property_id = %s ORDER BY point_id, profile_id", (property_id,))
    return {"property": prop, "listings": listings, "price_history": history, "commutes": routes}


def counts(db: Database) -> Row:
    row = db.fetch_one(
        "SELECT (SELECT count(*) FROM listings WHERE status = 'active') AS active_listings, "
        "(SELECT count(*) FROM properties p WHERE EXISTS "
        "(SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')) AS properties, "
        "(SELECT count(*) FROM listings WHERE status = 'active' AND detail_fetched_at IS NULL) AS detail_pending, "
        "(SELECT count(*) FROM search_areas WHERE enabled) AS areas, "
        "(SELECT count(*) FROM commute_points WHERE enabled) AS commute_points")
    assert row is not None
    return row
