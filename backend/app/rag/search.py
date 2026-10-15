"""Full-text search over advert wording (Postgres tsvector via v_property_text.search), run as the read-only role."""
from typing import Any

from app.db.database import Database

_SEARCH = """
SELECT t.property_id, p.address, p.borough, p.bedrooms, p.rent_pcm, p.url,
       ts_headline('english', coalesce(t.description, t.headline, ''), q.query,
                   'MaxFragments=2, MaxWords=24, MinWords=8, StartSel=[, StopSel=]') AS excerpt,
       round(ts_rank(t.search, q.query)::numeric, 3) AS relevance
FROM v_property_text t
JOIN v_properties p ON p.id = t.property_id
CROSS JOIN (SELECT websearch_to_tsquery('english', %s) AS query) q
WHERE t.search @@ q.query
ORDER BY ts_rank(t.search, q.query) DESC, p.rent_pcm
LIMIT %s
"""


def search_descriptions(db: Database, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Properties whose advert text matches `query`, best first, each with a short highlighted excerpt.

    `query` uses web-search syntax: words are ANDed, "double quotes" match a phrase, `or` alternates, `-word` excludes.
    """
    limit = max(1, min(limit, 25))
    with db.ro_conn() as c:
        rows = c.execute(_SEARCH, (query, limit)).fetchall()
        c.rollback()
    return [{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in r.items()} for r in rows]
