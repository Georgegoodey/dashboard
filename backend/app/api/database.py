"""Database management API: what is in Postgres (tables, views, columns) and which migrations have run."""
import asyncio
from typing import Any

from fastapi import APIRouter

from app.api.deps import Rt
from app.core.errors import InvalidInput
from app.db import migrate
from app.repositories import catalog

router = APIRouter(prefix="/api/database")


@router.get("")
def overview(rt: Rt) -> Any:
    info = catalog.overview(rt.db)
    state = migrate.status(rt.db, rt.settings.sqlalchemy_url)
    return {**info, "migrations": {"applied": [{"version": v, "applied_at": None} for v in state["applied"]],
                                   "pending": state["pending"]}}


@router.post("/migrate")
async def apply_migrations(rt: Rt) -> Any:
    """Apply every pending migration."""
    try:
        return {"applied": await asyncio.to_thread(migrate.upgrade, rt.db, rt.settings.sqlalchemy_url)}
    except Exception as e:
        raise InvalidInput(f"Migration failed: {type(e).__name__}: {e}") from e
