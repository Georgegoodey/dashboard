"""The properties list and detail (read from the curated views)."""
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import Rt
from app.core.errors import NotFound
from app.repositories import properties

router = APIRouter(prefix="/api")


@router.get("/properties")
def list_properties(
    rt: Rt,
    q: str | None = None, min_rent: float | None = None, max_rent: float | None = None,
    min_beds: int | None = None, max_beds: int | None = None, borough: str | None = None,
    furnish: Annotated[list[str] | None, Query()] = None, has: Annotated[list[str] | None, Query()] = None,
    commute: Annotated[list[str] | None, Query()] = None,
    sort: str = "newest", order: str = "asc", limit: int = Query(50, le=500), offset: int = 0,
) -> Any:
    furnish_in, has_in = properties.check_options(furnish, has)
    return properties.search(
        rt.db, q=q, min_rent=min_rent, max_rent=max_rent, min_beds=min_beds, max_beds=max_beds, borough=borough,
        commute=properties.parse_commute(rt.db, commute or []), furnish=furnish_in, has=has_in, sort=sort, order=order,
        limit=limit, offset=offset)


@router.get("/properties/map")      # declared before /properties/{property_id}, which would otherwise swallow "map"
def map_points(
    rt: Rt,
    q: str | None = None, min_rent: float | None = None, max_rent: float | None = None,
    min_beds: int | None = None, max_beds: int | None = None, borough: str | None = None,
    furnish: Annotated[list[str] | None, Query()] = None, has: Annotated[list[str] | None, Query()] = None,
    commute: Annotated[list[str] | None, Query()] = None,
) -> Any:
    furnish_in, has_in = properties.check_options(furnish, has)
    return properties.map_points(
        rt.db, q=q, min_rent=min_rent, max_rent=max_rent, min_beds=min_beds, max_beds=max_beds, borough=borough,
        commute=properties.parse_commute(rt.db, commute or []), furnish=furnish_in, has=has_in)


@router.get("/properties/{property_id}")
def property_detail(property_id: int, rt: Rt) -> Any:
    found = properties.detail(rt.db, property_id)
    if found is None:
        raise NotFound("Unknown property")
    return found
