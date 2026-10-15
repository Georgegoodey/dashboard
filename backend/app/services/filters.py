"""Search filters (minimum and maximum bedrooms, maximum rent): stored in app_settings and edited in the UI.
The enabled search areas are part of the same visibility rule: `apply` hides homes in areas that are switched off.

They are applied three ways so they behave the same for every portal: sent to the portal as search parameters,
re-checked on what comes back (`SearchFilters.accepts`), and applied to listings already stored (`apply`), which are
marked 'filtered' (hidden everywhere) rather than deleted, so loosening a filter brings them straight back.
"""
from app.core.errors import InvalidInput
from app.db.database import Database
from app.repositories import app_settings, listings
from app.sources.base import SearchFilters

KEY = "search_filters"


def load(db: Database) -> SearchFilters:
    value = app_settings.get(db, KEY)
    defaults = SearchFilters()
    return SearchFilters(
        min_bedrooms=value.get("min_bedrooms", defaults.min_bedrooms),
        max_bedrooms=value.get("max_bedrooms", defaults.max_bedrooms),
        max_rent=value.get("max_rent", defaults.max_rent),
    )


def save(db: Database, f: SearchFilters) -> None:
    app_settings.put(db, KEY, f.as_dict())


def apply(db: Database, f: SearchFilters) -> dict[str, int]:
    """Hide stored listings outside the filters or the enabled areas, and restore ones that are inside again."""
    return listings.apply_filters(db, f)


def refresh(db: Database) -> dict[str, int]:
    """Re-apply the saved filters; call after the search areas change."""
    return apply(db, load(db))


def update(db: Database, f: SearchFilters) -> dict[str, int]:
    """Validate, store, and sweep the stored listings. Returns how many were hidden and restored."""
    if f.min_bedrooms is not None and f.max_bedrooms is not None and f.min_bedrooms > f.max_bedrooms:
        raise InvalidInput("Minimum bedrooms cannot be more than maximum bedrooms")
    save(db, f)
    return apply(db, f)
