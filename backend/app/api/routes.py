from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agents.agent import stream_chat
from app.charts.infer import infer
from app.db import datasets, sqlguard
from app.db.database import db
from app.rag import ingest as rag_ingest
from app.rag.retrieve import search

router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    session_id: str
    message: str


class SearchIn(BaseModel):
    query: str
    k: int = 5


class SqlIn(BaseModel):
    sql: str


@router.post("/chat")
async def chat(body: ChatIn):
    return EventSourceResponse(stream_chat(body.session_id, body.message))


@router.get("/documents")
def list_documents():
    with db() as con:
        rows = con.execute(
            "SELECT id, filename, n_chunks, created_at FROM documents ORDER BY id DESC"
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "n_chunks": r[2], "created_at": str(r[3])} for r in rows]


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return await run_in_threadpool(rag_ingest.ingest, file.filename or "upload", file.content_type, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int):
    rag_ingest.delete_document(doc_id)
    return {"ok": True}


@router.post("/search")
async def search_endpoint(body: SearchIn):
    return await run_in_threadpool(search, body.query, body.k)


@router.post("/sql")
def sql_endpoint(body: SqlIn):
    try:
        return sqlguard.run_readonly(body.sql)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/datasets")
def list_datasets():
    return datasets.list_datasets()


@router.post("/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    from app.core.config import settings

    dest = settings.resolve(settings.upload_dir) / (file.filename or "data.csv")
    dest.write_bytes(await file.read())
    try:
        return await run_in_threadpool(datasets.load_file, dest)
    except Exception as e:
        raise HTTPException(400, f"Could not load dataset: {e}")


@router.delete("/datasets/{table}")
def drop_dataset(table: str):
    if table not in datasets.user_tables():
        raise HTTPException(404, "Unknown table")
    with db() as con:
        con.execute(f'DROP TABLE "{table}"')
    return {"ok": True}


@router.post("/chart")
def chart_endpoint(body: SqlIn):
    """Run read-only SQL and return the result plus its inferred chart spec (the one pipeline all charts use)."""
    try:
        result = sqlguard.run_readonly(body.sql)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {**result, **infer(result["columns"], result["types"], result["rows"])}
