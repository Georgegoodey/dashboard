"""Settings you enter in the UI: search areas, home and work, commute times, search filters."""
from datetime import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import Rt
from app.core.errors import InvalidInput, NotFound
from app.pipeline.normalise import OUTCODE_RE
from app.repositories import areas, places, profiles
from app.services import filters, postcodes
from app.sources.base import SearchFilters

router = APIRouter(prefix="/api")


# ── search areas ──────────────────────────────────────────────────────────────────────────────────────────────

class AreaIn(BaseModel):
    outcode: str
    label: str | None = None
    enabled: bool = True


class AreaUpdate(BaseModel):
    label: str | None = None
    enabled: bool = True


@router.get("/areas")
def list_areas(rt: Rt) -> Any:
    return areas.list_all(rt.db)


@router.post("/areas")
def add_area(body: AreaIn, rt: Rt) -> Any:
    outcode = body.outcode.strip().upper()
    if not OUTCODE_RE.match(outcode):
        raise InvalidInput(f"'{body.outcode}' is not a UK outcode such as SW11 or TW9")
    area_id = areas.upsert(rt.db, outcode, body.label or outcode, body.enabled)
    return {"id": area_id, "outcode": outcode, **filters.refresh(rt.db)}


@router.put("/areas/{area_id}")
def update_area(area_id: int, body: AreaUpdate, rt: Rt) -> Any:
    if not areas.update(rt.db, area_id, body.label, body.enabled):
        raise NotFound("Unknown area")
    return {"ok": True, **filters.refresh(rt.db)}


@router.delete("/areas/{area_id}")
def delete_area(area_id: int, rt: Rt) -> Any:
    areas.delete(rt.db, area_id)
    return {"ok": True, **filters.refresh(rt.db)}


# ── home and work ─────────────────────────────────────────────────────────────────────────────────────────────

class PlaceIn(BaseModel):
    postcode: str
    label: str | None = None
    address: str | None = None


def _kind(kind: str) -> str:
    if kind not in ("home", "work"):
        raise NotFound("Place kind must be 'home' or 'work'")
    return kind


@router.get("/places")
def list_places(rt: Rt) -> Any:
    return places.list_all(rt.db)


@router.put("/places/{kind}")
async def set_place(kind: str, body: PlaceIn, rt: Rt) -> Any:
    return await postcodes.set_place(rt.db, _kind(kind), body.postcode, body.label, body.address)


@router.delete("/places/{kind}")
def delete_place(kind: str, rt: Rt) -> Any:
    places.delete(rt.db, kind)
    return {"ok": True}


# ── commute profiles ──────────────────────────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    local_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(ge=0, le=6)
    enabled: bool = True


@router.get("/profiles")
def list_profiles(rt: Rt) -> Any:
    rows = profiles.list_all(rt.db)
    for r in rows:
        r["local_time"] = r["local_time"].strftime("%H:%M")
    return rows


@router.put("/profiles/{slug}")
def update_profile(slug: str, body: ProfileIn, rt: Rt) -> Any:
    try:
        t = time.fromisoformat(body.local_time)
    except ValueError:
        raise InvalidInput("Time must be HH:MM") from None
    if not profiles.update(rt.db, slug, t, body.weekday, body.enabled):
        raise NotFound("Unknown profile")
    return {"ok": True}


# ── search filters ────────────────────────────────────────────────────────────────────────────────────────────

class FiltersIn(BaseModel):
    """None means no limit."""
    min_bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_rent: int | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/filters")
def get_filters(rt: Rt) -> Any:
    return filters.load(rt.db).as_dict()


@router.put("/filters")
def set_filters(body: FiltersIn, rt: Rt) -> Any:
    f = SearchFilters(min_bedrooms=body.min_bedrooms, max_bedrooms=body.max_bedrooms, max_rent=body.max_rent)
    return {**f.as_dict(), **filters.update(rt.db, f)}    # hidden / restored counts for listings already stored
