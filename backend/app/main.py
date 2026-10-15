import json
import logging
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import scheduler
from app.api.lettings import router as lettings_router
from app.api.routes import router
from app.core.config import settings
from app.db import pg
from app.db.database import init_db

log = logging.getLogger("app")
db_state = {"ok": False, "error": "not started", "migrations": []}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()                                   # legacy DuckDB (uploaded datasets)
    try:
        pg.init_pools()
        db_state["migrations"] = pg.migrate()
        db_state.update(ok=True, error="")
        if settings.scheduler_enabled:
            await scheduler.start()
    except Exception as e:                      # Postgres not running: the API still starts and says why
        log.exception("Postgres unavailable")
        db_state.update(ok=False, error=f"{type(e).__name__}: {e}")
    yield
    await scheduler.stop()
    pg.close_pools()


app = FastAPI(title="Dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(lettings_router)


def _llm_status() -> tuple[bool, str]:
    """(configured, reason). Never raises: a missing LLM must not take the API down."""
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return (True, "") if settings.anthropic_api_key else (False, "ANTHROPIC_API_KEY is not set")
    if provider == "ollama":
        try:
            with urllib.request.urlopen(f"{settings.llm_base_url.rstrip('/')}/api/tags", timeout=2) as r:
                names = {m.get("name") for m in json.load(r).get("models", [])}
        except Exception as e:
            return False, f"Ollama not reachable at {settings.llm_base_url} ({type(e).__name__})"
        wanted = settings.llm_model
        if wanted in names or (":" not in wanted and f"{wanted}:latest" in names):
            return True, ""
        return False, f"model '{wanted}' is not pulled (run: ollama pull {wanted})"
    return False, f"unknown LLM_PROVIDER '{settings.llm_provider}'"


@app.get("/health")
def health():
    configured, reason = _llm_status()
    return {
        "status": "ok",
        "llm_configured": configured,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_reason": reason,
        "tfl_key_configured": bool(settings.tfl_app_key),
        "database_ok": db_state["ok"],
        "database_error": db_state["error"],
    }
