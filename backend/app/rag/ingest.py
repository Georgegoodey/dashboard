import io

from app.core.config import settings
from app.db.database import db
from app.rag.chunk import chunk_text
from app.rag.embed import embed


def extract_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader

        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", errors="replace")


def rebuild_fts() -> None:
    with db() as con:
        try:
            con.execute(
                "PRAGMA create_fts_index('chunks', 'id', 'text', stemmer='porter', overwrite=1)"
            )
        except Exception:
            pass


def ingest(filename: str, content_type: str | None, data: bytes) -> dict:
    text = extract_text(filename, data)
    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise ValueError("No extractable text in file")
    vectors = embed(chunks)
    with db() as con:
        doc_id = con.execute(
            "INSERT INTO documents (filename, content_type, n_chunks) VALUES (?, ?, ?) RETURNING id",
            [filename, content_type, len(chunks)],
        ).fetchone()[0]
        con.executemany(
            "INSERT INTO chunks (document_id, chunk_index, text, embedding) VALUES (?, ?, ?, ?)",
            [[doc_id, i, c, v] for i, (c, v) in enumerate(zip(chunks, vectors))],
        )
    rebuild_fts()
    return {"id": doc_id, "filename": filename, "n_chunks": len(chunks)}


def delete_document(doc_id: int) -> None:
    with db() as con:
        con.execute("DELETE FROM chunks WHERE document_id = ?", [doc_id])
        con.execute("DELETE FROM documents WHERE id = ?", [doc_id])
    rebuild_fts()
