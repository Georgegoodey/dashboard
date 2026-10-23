"""Settings you enter in the UI: search areas, commute points and their journeys, search filters."""
from datetime import time
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import Rt
from app.core.errors import InvalidInput, NotFound
from app.pipeline.normalise import OUTCODE_RE
from app.repositories import areas, commute_points
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


# ── commute points and their journeys ─────────────────────────────────────────────────────────────────────────

Direction = Literal["to_place", "from_place"]
Anchor = Literal["arrive_by", "depart_at"]


class JourneyIn(BaseModel):
    direction: Direction = "to_place"
    anchor: Anchor = "arrive_by"
    local_time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=1, ge=0, le=6)
    enabled: bool = True


class PointIn(BaseModel):
    postcode: str
    label: str | None = None
    address: str | None = None
    am_pm: bool = False              # add the way back as well (leave at 18:00)
    local_time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=1, ge=0, le=6)


class PointUpdate(BaseModel):
    label: str
    address: str | None = None
    postcode: str | None = None      # only sent when it changes
    enabled: bool = True


def _time(text: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise InvalidInput("Time must be HH:MM") from None


def _journeys(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "local_time": r["local_time"].strftime("%H:%M")} for r in rows]


@router.get("/commute-points")
def list_commute_points(rt: Rt) -> Any:
    return [{**p, "journeys": _journeys(p["journeys"])} for p in commute_points.list_all(rt.db)]


@router.post("/commute-points")
async def add_commute_point(body: PointIn, rt: Rt) -> Any:
    start = _time(body.local_time)
    found = await postcodes.locate(rt.http, body.postcode)
    journeys = [{**commute_points.TO_POINT, "local_time": start, "weekday": body.weekday}]
    if body.am_pm:
        journeys.append({**commute_points.FROM_POINT, "weekday": body.weekday})
    point_id = commute_points.add(rt.db, (body.label or "").strip() or found["postcode"], body.address, found["postcode"],
                                  found["lat"], found["lon"], journeys)
    return {"id": point_id, "postcode": found["postcode"], "borough": found["borough"]}


@router.put("/commute-points/{point_id}")
async def update_commute_point(point_id: int, body: PointUpdate, rt: Rt) -> Any:
    label = body.label.strip()
    if not label:
        raise InvalidInput("A commute point needs a name")
    place = None
    if body.postcode:
        found = await postcodes.locate(rt.http, body.postcode)
        place = (found["postcode"], found["lat"], found["lon"])
    if not commute_points.update(rt.db, point_id, label, body.address, body.enabled, place):
        raise NotFound("Unknown commute point")
    return {"ok": True}


@router.delete("/commute-points/{point_id}")
def delete_commute_point(point_id: int, rt: Rt) -> Any:
    commute_points.delete(rt.db, point_id)
    return {"ok": True}


@router.post("/commute-points/{point_id}/journeys")
def add_journey(point_id: int, body: JourneyIn, rt: Rt) -> Any:
    journey_id = commute_points.add_journey(rt.db, point_id, body.direction, body.anchor, _time(body.local_time), body.weekday)
    if journey_id is None:
        raise NotFound("Unknown commute point")
    return {"id": journey_id}


@router.put("/journeys/{journey_id}")
def update_journey(journey_id: int, body: JourneyIn, rt: Rt) -> Any:
    if not commute_points.update_journey(rt.db, journey_id, body.direction, body.anchor, _time(body.local_time),
                                         body.weekday, body.enabled):
        raise NotFound("Unknown journey")
    return {"ok": True}


@router.delete("/journeys/{journey_id}")
def delete_journey(journey_id: int, rt: Rt) -> Any:
    commute_points.delete_journey(rt.db, journey_id)
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
