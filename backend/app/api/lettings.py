"""REST API for the lettings app: settings you enter, scheduler jobs, and the properties list."""
import asyncio
from datetime import datetime, time

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import scheduler
from app.db import pg
from app.jobs import runner
from app.pipeline import enrich, filters as filters_mod
from app.pipeline.normalise import OUTCODE_RE, normalise_postcode
from app.sources.base import SearchFilters

router = APIRouter(prefix="/api")


# ── search areas ──────────────────────────────────────────────────────────────────────────────────────────────────

class AreaIn(BaseModel):
    outcode: str
    label: str | None = None
    enabled: bool = True


@router.get("/areas")
def list_areas():
    return pg.fetch_all(
        "SELECT a.id, a.label, a.outcode, a.enabled, "
        "(SELECT count(*) FROM properties p WHERE p.outcode = a.outcode) AS properties "
        "FROM search_areas a ORDER BY a.outcode")


@router.post("/areas")
def add_area(body: AreaIn):
    outcode = body.outcode.strip().upper()
    if not OUTCODE_RE.match(outcode):
        raise HTTPException(400, f"'{body.outcode}' is not a UK outcode such as SW11 or TW9")
    row = pg.fetch_one(
        "INSERT INTO search_areas (label, outcode, enabled) VALUES (%s, %s, %s) "
        "ON CONFLICT (outcode) DO UPDATE SET label = EXCLUDED.label, enabled = EXCLUDED.enabled RETURNING id",
        (body.label or outcode, outcode, body.enabled))
    return {"id": row["id"], "outcode": outcode}


class AreaUpdate(BaseModel):
    label: str | None = None
    enabled: bool = True


@router.put("/areas/{area_id}")
def update_area(area_id: int, body: AreaUpdate):
    n = pg.execute("UPDATE search_areas SET label = coalesce(%s, label), enabled = %s WHERE id = %s",
                   (body.label, body.enabled, area_id))
    if not n:
        raise HTTPException(404, "Unknown area")
    return {"ok": True}


@router.delete("/areas/{area_id}")
def delete_area(area_id: int):
    pg.execute("DELETE FROM search_areas WHERE id = %s", (area_id,))
    return {"ok": True}


# ── home and work ─────────────────────────────────────────────────────────────────────────────────────────────────

class PlaceIn(BaseModel):
    postcode: str
    label: str | None = None
    address: str | None = None


@router.get("/places")
def list_places():
    return pg.fetch_all(
        "SELECT kind, label, address, postcode, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM places ORDER BY kind")


@router.put("/places/{kind}")
async def set_place(kind: str, body: PlaceIn):
    if kind not in ("home", "work"):
        raise HTTPException(404, "Place kind must be 'home' or 'work'")
    pc = normalise_postcode(body.postcode)
    if not pc:
        raise HTTPException(400, f"'{body.postcode}' is not a full UK postcode, e.g. SW11 7FD")
    async with httpx.AsyncClient(timeout=20) as client:
        geo = await enrich.geocode(client, pc)
    if not geo or geo.get("latitude") is None:
        raise HTTPException(400, f"postcodes.io does not know {pc}")
    await asyncio.to_thread(_save_place, kind, body.label or kind.title(), body.address, pc, geo["latitude"], geo["longitude"])
    return {"kind": kind, "postcode": pc, "lat": geo["latitude"], "lon": geo["longitude"], "borough": geo.get("admin_district")}


def _save_place(kind: str, label: str, address: str | None, postcode: str, lat: float, lon: float) -> None:
    with pg.conn() as c:
        c.execute(
            "INSERT INTO places (kind, label, address, postcode, geom) VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) "
            "ON CONFLICT (kind) DO UPDATE SET label = EXCLUDED.label, address = EXCLUDED.address, postcode = EXCLUDED.postcode, "
            "geom = EXCLUDED.geom, updated_at = now()", (kind, label, address, postcode, lon, lat))
        # routes to the old place are now wrong
        c.execute("DELETE FROM commute_routes WHERE profile_id IN (SELECT id FROM commute_profiles WHERE place_kind = %s)", (kind,))


@router.delete("/places/{kind}")
def delete_place(kind: str):
    with pg.conn() as c:
        c.execute("DELETE FROM commute_routes WHERE profile_id IN (SELECT id FROM commute_profiles WHERE place_kind = %s)", (kind,))
        c.execute("DELETE FROM places WHERE kind = %s", (kind,))
    return {"ok": True}


# ── commute profiles ──────────────────────────────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    local_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(ge=0, le=6)
    enabled: bool = True


@router.get("/profiles")
def list_profiles():
    rows = pg.fetch_all("SELECT slug, label, place_kind, direction, anchor, local_time, weekday, enabled FROM commute_profiles ORDER BY id")
    for r in rows:
        r["local_time"] = r["local_time"].strftime("%H:%M")
    return rows


@router.put("/profiles/{slug}")
def update_profile(slug: str, body: ProfileIn):
    try:
        t = time.fromisoformat(body.local_time)
    except ValueError:
        raise HTTPException(400, "Time must be HH:MM")
    with pg.conn() as c:
        row = c.execute("UPDATE commute_profiles SET local_time = %s, weekday = %s, enabled = %s WHERE slug = %s RETURNING id",
                        (t, body.weekday, body.enabled, slug)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown profile")
        c.execute("DELETE FROM commute_routes WHERE profile_id = %s", (row["id"],))   # times changed, so recompute
    return {"ok": True}


# ── jobs ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class JobIn(BaseModel):
    enabled: bool
    interval_minutes: int = Field(ge=1, le=60 * 24 * 7)
    active_from: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    active_to: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


def _hhmm(t) -> str | None:
    return t.strftime("%H:%M") if t else None


@router.get("/jobs")
def list_jobs():
    out = []
    for job in runner.JOBS.values():
        cfg = runner.get_setting(job.id)
        last = pg.fetch_one("SELECT * FROM job_runs WHERE job_id = %s ORDER BY started_at DESC LIMIT 1", (job.id,))
        ok = pg.fetch_one("SELECT max(finished_at) AS t FROM job_runs WHERE job_id = %s AND status = 'ok'", (job.id,))
        nxt = scheduler.next_run_time(job.id)
        out.append({
            "id": job.id, "title": job.title, "description": job.description,
            "enabled": cfg.get("enabled", True), "interval_minutes": cfg.get("interval_minutes", job.default_interval_minutes),
            "active_from": _hhmm(cfg.get("active_from")), "active_to": _hhmm(cfg.get("active_to")),
            "running": runner.is_running(job.id),
            "next_run": nxt.isoformat() if nxt else None,
            "last_ok": ok["t"].isoformat() if ok and ok["t"] else None,
            "last_run": None if not last else {
                "started_at": last["started_at"].isoformat(), "finished_at": last["finished_at"].isoformat() if last["finished_at"] else None,
                "status": last["status"], "trigger": last["trigger"], "rows_added": last["rows_added"],
                "rows_updated": last["rows_updated"], "detail": last["detail"], "error": last["error"]},
        })
    return out


@router.put("/jobs/{job_id}")
def update_job(job_id: str, body: JobIn):
    if job_id not in runner.JOBS:
        raise HTTPException(404, "Unknown job")
    pg.execute(
        "UPDATE job_settings SET enabled = %s, interval_minutes = %s, active_from = %s, active_to = %s, updated_at = now() WHERE job_id = %s",
        (body.enabled, body.interval_minutes, body.active_from, body.active_to, job_id))
    scheduler.reschedule(job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/run", status_code=202)
async def run_job_now(job_id: str):
    if job_id not in runner.JOBS:
        raise HTTPException(404, "Unknown job")
    if runner.is_running(job_id):
        raise HTTPException(409, "Already running")
    task = asyncio.create_task(runner.run_job(job_id, "manual"))
    scheduler._catchup_tasks.add(task)            # keep a reference so the task is not garbage-collected mid-run
    task.add_done_callback(scheduler._catchup_tasks.discard)
    return {"started": job_id}


@router.get("/jobs/runs")
def recent_runs(limit: int = Query(30, le=200)):
    rows = pg.fetch_all("SELECT id, job_id, started_at, finished_at, status, trigger, rows_added, rows_updated, error "
                        "FROM job_runs ORDER BY started_at DESC LIMIT %s", (limit,))
    return [{**r, "started_at": r["started_at"].isoformat(), "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None}
            for r in rows]


# ── status and properties ─────────────────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def status():
    row = pg.fetch_one(
        "SELECT (SELECT count(*) FROM listings WHERE status = 'active') AS active_listings, "
        "(SELECT count(*) FROM properties p WHERE EXISTS (SELECT 1 FROM listings l WHERE l.property_id = p.id AND l.status = 'active')) AS properties, "
        "(SELECT count(*) FROM listings WHERE status = 'active' AND detail_fetched_at IS NULL) AS detail_pending, "
        "(SELECT count(*) FROM search_areas WHERE enabled) AS areas, "
        "(SELECT count(*) FROM places) AS places")
    from app.commute import service
    row["commute_pending"] = service.count_pending()
    return row


SORTS = {
    "rent": "rent_pcm", "commute": "work_am_min", "newest": "days_on_market", "bedrooms": "bedrooms",
    "vs_median": "rent_vs_median_pct", "distance_work": "distance_to_work_km",
}


@router.get("/properties")
def list_properties(
    q: str | None = None, min_rent: float | None = None, max_rent: float | None = None,
    min_beds: int | None = None, max_beds: int | None = None, borough: str | None = None,
    max_commute: int | None = None, furnished: str | None = None,
    sort: str = "newest", order: str = "asc", limit: int = Query(50, le=500), offset: int = 0,
):
    where, params = ["true"], []
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
    col = SORTS.get(sort, "days_on_market")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    clause = " AND ".join(where)
    total = pg.fetch_one(f"SELECT count(*) AS n FROM v_properties WHERE {clause}", params)["n"]
    rows = pg.fetch_all(
        f"SELECT * FROM v_properties WHERE {clause} ORDER BY {col} {direction} NULLS LAST, id LIMIT %s OFFSET %s",
        params + [limit, offset])
    return {"total": total, "rows": rows}


@router.get("/properties/{property_id}")
def property_detail(property_id: int):
    prop = pg.fetch_one("SELECT * FROM v_properties WHERE id = %s", (property_id,))
    if not prop:
        raise HTTPException(404, "Unknown property")
    listings = pg.fetch_all(
        "SELECT s.name AS source, l.url, l.status, l.rent_pcm, l.deposit, l.furnished, l.let_type, l.min_term_months, "
        "l.available_from, l.agent_name, l.headline, l.description, l.key_features, l.first_seen, l.last_seen "
        "FROM listings l JOIN sources s ON s.id = l.source_id WHERE l.property_id = %s ORDER BY l.status, l.rent_pcm", (property_id,))
    history = pg.fetch_all(
        "SELECT h.observed_at, h.rent_pcm, h.status FROM listing_price_history h JOIN listings l ON l.id = h.listing_id "
        "WHERE l.property_id = %s ORDER BY h.observed_at", (property_id,))
    routes = pg.fetch_all(
        "SELECT DISTINCT ON (cp.slug) cp.slug, cp.label, r.ref_date, r.duration_min, r.walk_min, r.transfers, r.fare_pence, r.summary "
        "FROM commute_routes r JOIN commute_profiles cp ON cp.id = r.profile_id WHERE r.property_id = %s "
        "ORDER BY cp.slug, r.ref_date DESC", (property_id,))
    return {"property": prop, "listings": listings, "price_history": history, "commutes": routes}


# ── search filters ────────────────────────────────────────────────────────────────────────────────────────────────

class FiltersIn(BaseModel):
    """None means no limit."""
    min_bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_rent: int | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/filters")
def get_filters():
    return filters_mod.load().as_dict()


@router.put("/filters")
def set_filters(body: FiltersIn):
    if body.min_bedrooms is not None and body.max_bedrooms is not None and body.min_bedrooms > body.max_bedrooms:
        raise HTTPException(400, "Minimum bedrooms cannot be more than maximum bedrooms")
    f = SearchFilters(min_bedrooms=body.min_bedrooms, max_bedrooms=body.max_bedrooms, max_rent=body.max_rent)
    filters_mod.save(f)
    return {**f.as_dict(), **filters_mod.apply_to_existing(f)}    # hidden / restored counts for listings already stored
