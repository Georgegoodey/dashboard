"""Per-portal figures for the Jobs panel."""
from typing import Any

from app.db.database import Database


def stats(db: Database) -> list[dict[str, Any]]:
    """One row per source: what is stored from it, how much of it is new, and how far its areas have been scraped."""
    rows = db.fetch_all(
        "SELECT s.name, s.enabled, "
        "  count(l.id) FILTER (WHERE l.status = 'active') AS active, "
        "  count(l.id) FILTER (WHERE l.status = 'withdrawn') AS withdrawn, "
        "  count(l.id) FILTER (WHERE l.first_seen > now() - interval '24 hours') AS new_24h, "
        "  count(l.id) FILTER (WHERE l.first_seen > now() - interval '7 days') AS new_7d, "
        "  count(l.id) FILTER (WHERE l.status = 'active' AND l.detail_fetched_at IS NULL) AS detail_pending, "
        "  percentile_cont(0.5) WITHIN GROUP (ORDER BY l.rent_pcm) FILTER (WHERE l.status = 'active') AS median_rent, "
        "  (SELECT count(*) FROM search_areas a WHERE a.enabled AND a.scraped_at ->> s.name IS NOT NULL) AS areas_done, "
        "  (SELECT max((a.scraped_at ->> s.name)::timestamptz) FROM search_areas a WHERE a.enabled) AS last_scraped "
        "FROM sources s LEFT JOIN listings l ON l.source_id = s.id GROUP BY s.id ORDER BY s.id")
    total = db.fetch_one("SELECT count(*) AS n FROM search_areas WHERE enabled")
    areas_total = int(total["n"]) if total else 0
    return [{
        "name": r["name"], "enabled": r["enabled"], "active": r["active"], "withdrawn": r["withdrawn"],
        "new_24h": r["new_24h"], "new_7d": r["new_7d"], "detail_pending": r["detail_pending"],
        "median_rent": None if r["median_rent"] is None else round(float(r["median_rent"])),
        "areas_done": r["areas_done"], "areas_total": areas_total,
        "last_scraped": r["last_scraped"].isoformat() if r["last_scraped"] else None,
    } for r in rows]
