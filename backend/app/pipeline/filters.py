"""Search filters (minimum and maximum bedrooms, maximum rent): stored in app_settings and edited in the UI.

They are applied three ways so they behave the same for every portal: sent to the portal as search parameters,
re-checked on what comes back (`SearchFilters.accepts`), and applied to listings already stored
(`apply_to_existing`), which are marked 'filtered' (hidden everywhere) rather than deleted, so loosening a filter
brings them straight back.
"""
import json

from app.db import pg
from app.sources.base import SearchFilters

KEY = "search_filters"


def load() -> SearchFilters:
    row = pg.fetch_one("SELECT value FROM app_settings WHERE key = %s", (KEY,))
    value = row["value"] if row else {}
    if isinstance(value, str):
        value = json.loads(value)
    defaults = SearchFilters()
    return SearchFilters(
        min_bedrooms=value.get("min_bedrooms", defaults.min_bedrooms),
        max_bedrooms=value.get("max_bedrooms", defaults.max_bedrooms),
        max_rent=value.get("max_rent", defaults.max_rent),
    )


def save(f: SearchFilters) -> None:
    pg.execute(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (KEY, json.dumps(f.as_dict())),
    )


_OUTSIDE = (
    "((%(min_b)s::int IS NOT NULL AND p.bedrooms IS NOT NULL AND p.bedrooms < %(min_b)s::int) "
    "OR (%(max_b)s::int IS NOT NULL AND p.bedrooms IS NOT NULL AND p.bedrooms > %(max_b)s::int) "
    "OR (%(max_r)s::numeric IS NOT NULL AND l.rent_pcm IS NOT NULL AND l.rent_pcm > %(max_r)s::numeric * 1.01))"
)


def sql_params(f: SearchFilters) -> dict:
    return {"min_b": f.min_bedrooms, "max_b": f.max_bedrooms, "max_r": f.max_rent}


def inside_clause() -> str:
    """SQL condition (for queries aliasing listings as l and properties as p) that is true when a listing passes."""
    return f"NOT {_OUTSIDE}"


def apply_to_existing(f: SearchFilters) -> dict[str, int]:
    """Hide stored listings outside the filters and restore ones that are inside again."""
    params = sql_params(f)
    with pg.conn() as c:
        hidden = c.execute(
            "UPDATE listings l SET status = 'filtered' FROM properties p "
            f"WHERE p.id = l.property_id AND l.status = 'active' AND {_OUTSIDE}", params).rowcount
        restored = c.execute(
            "UPDATE listings l SET status = 'active', missed_scrapes = 0 FROM properties p "
            f"WHERE p.id = l.property_id AND l.status = 'filtered' AND NOT {_OUTSIDE}", params).rowcount
    return {"hidden": hidden, "restored": restored}
