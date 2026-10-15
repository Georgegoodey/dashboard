"""Turn domain and infrastructure errors into HTTP responses."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from app.core.errors import DomainError
from app.db.database import DatabaseUnavailable


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeout)
    @app.exception_handler(DatabaseUnavailable)
    async def _database_down(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": f"Postgres unavailable: {type(exc).__name__}: {exc}"}, status_code=503)
