"""Duplicates: the same home advertised on several portals. Look at what would be merged, then merge."""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import Rt
from app.services import dedupe

router = APIRouter(prefix="/api")
SAMPLES = 8


class AutoIn(BaseModel):
    auto: bool


@router.get("/dedupe")
def preview(rt: Rt) -> Any:
    """What merging would do now, with a few example groups. Changes nothing."""
    found = dedupe.plan(rt.db)
    return {"auto": dedupe.auto_enabled(rt.db), "merged_total": dedupe.merged_total(rt.db), "preview": found.summary(),
            "samples": dedupe.describe(rt.db, found.clusters[:SAMPLES])}


@router.put("/dedupe")
def set_auto(body: AutoIn, rt: Rt) -> Any:
    """Switch on or off merging by the scheduled job. Off by default."""
    dedupe.set_auto(rt.db, body.auto)
    return {"auto": body.auto}


@router.post("/dedupe/apply")
def apply_now(rt: Rt) -> Any:
    """Merge every group found now."""
    return dedupe.apply(rt.db)
