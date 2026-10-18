from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import database, health, jobs, properties, query, settings_routes
from app.api.errors import register_error_handlers
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.runtime import Runtime, set_runtime


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings or Runtime; production uses the environment."""
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)
    rt = runtime or Runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        set_runtime(rt)
        await rt.start()
        yield
        await rt.stop()
        set_runtime(None)

    # In production the interactive docs and the schema are off: nothing needs them there, and they list every endpoint.
    production = settings.environment == "production"
    app = FastAPI(
        title="Lettings API", lifespan=lifespan,
        docs_url=None if production else "/docs", redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.state.runtime = rt
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)
    for module in (health, settings_routes, jobs, properties, query, database):
        app.include_router(module.router)
    return app


app = create_app()
