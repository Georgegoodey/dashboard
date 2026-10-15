"""Hybrid retrieval: cosine vector search + BM25 full-text, merged with reciprocal rank fusion."""
from app.core.config import settings
from app.db.database import db
from app.rag.embed import embed

RRF_K = 60


def _vector(q: str, limit: int) -> list[int]:
    qv = embed([q])[0]
    with db() as con:
        rows = con.execute(
            f"""SELECT id FROM chunks
                ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{settings.embedding_dim}]) DESC
                LIMIT ?""",
            [qv, limit],
        ).fetchall()
    return [r[0] for r in rows]


def _keyword(q: str, limit: int) -> list[int]:
    with db() as con:
        try:
            rows = con.execute(
                """SELECT id FROM (
                       SELECT id, fts_main_chunks.match_bm25(id, ?) AS score FROM chunks
                   ) WHERE score IS NOT NULL ORDER BY score DESC LIMIT ?""",
                [q, limit],
            ).fetchall()
        except Exception:
            return []
    return [r[0] for r in rows]


def search(q: str, k: int = 5) -> list[dict]:
    scores: dict[int, float] = {}
    for ranking in (_vector(q, k * 3), _keyword(q, k * 3)):
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    if not top:
        return []
    with db() as con:
        rows = con.execute(
            f"""SELECT c.id, c.text, c.chunk_index, d.filename FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({",".join("?" * len(top))})""",
            top,
        ).fetchall()
    by_id = {r[0]: r for r in rows}
    return [
        {"chunk_id": cid, "text": by_id[cid][1], "chunk_index": by_id[cid][2],
         "filename": by_id[cid][3], "score": round(scores[cid], 5)}
        for cid in top if cid in by_id
    ]
