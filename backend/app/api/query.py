"""Read-only SQL, charts, and the chat stream."""
import asyncio
from typing import Any

import psycopg
from fastapi import APIRouter
from psycopg_pool import PoolTimeout
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import Rt
from app.charts.infer import infer
from app.core.errors import InvalidInput
from app.db import sqlguard
from app.runtime import Runtime

router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    session_id: str
    message: str


class SqlIn(BaseModel):
    sql: str


@router.post("/chat")
async def chat(body: ChatIn, rt: Rt) -> Any:
    return EventSourceResponse(rt.chat.stream(body.session_id, body.message))


def _run(rt: Runtime, sql: str) -> dict[str, Any]:
    """Run read-only SQL for the console and charts. Anything wrong with the query itself is a 400 the author can read."""
    try:
        return sqlguard.run_readonly(rt.db, sql)
    except PoolTimeout:
        raise                                            # the database is unreachable: handled as 503
    except (sqlguard.SqlRejected, psycopg.Error) as e:
        raise InvalidInput(str(e).strip()) from e


@router.post("/sql")
async def sql_endpoint(body: SqlIn, rt: Rt) -> Any:
    return await asyncio.to_thread(_run, rt, body.sql)


@router.post("/chart")
async def chart_endpoint(body: SqlIn, rt: Rt) -> Any:
    """Run read-only SQL and return the result plus its inferred chart spec (the one pipeline all charts use)."""
    result = await asyncio.to_thread(_run, rt, body.sql)
    return {**result, **infer(result["columns"], result["types"], result["rows"])}
