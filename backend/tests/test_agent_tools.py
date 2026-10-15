"""The assistant's tools and retrieval, against real data."""
import json

import pytest

from app.agents.tools import MAX_SQL_ERRORS, build_tools, reset_sql_errors
from app.db.database import Database
from app.rag.schema import SchemaContext
from app.rag.search import search_descriptions
from app.repositories import listings
from tests.test_repositories import raw

pytestmark = pytest.mark.integration


def add(db: Database, listing_id: str, description: str, rent: str = "2000", address: str = "") -> int:
    lid, pid = listings.insert_new(db, raw(listing_id, rent=rent, address=address or f"{listing_id} Road"))
    detail = raw(listing_id, rent=rent, address=address or f"{listing_id} Road", description=description, has_detail=True)
    detail.headline = description.split(".")[0]
    listings.save_detail(db, lid, detail)
    return pid


def tools(db: Database) -> dict[str, object]:
    return {t.name: t for t in build_tools(db, SchemaContext(db))}


def test_schema_context_describes_the_views_and_hides_search_plumbing(db: Database) -> None:
    add(db, "1", "Bright flat with a garden.")
    text = SchemaContext(db).text()
    for view in ("v_properties", "v_price_changes", "v_property_text", "v_job_runs"):
        assert f"VIEW {view}" in text
    assert "rent_pcm" in text and "Monthly rent in GBP" in text and "range:" in text         # comments and ranges are included
    assert "sample rows" in text
    assert "tsvector" not in text and "  - search " not in text                              # the tsvector column is not exposed


def test_schema_context_is_cached(db: Database) -> None:
    ctx = SchemaContext(db, ttl_seconds=3600)
    first = ctx.text()
    add(db, "1", "Anything.")
    assert ctx.text() is first


def test_full_text_search_ranks_and_highlights(db: Database) -> None:
    garden = add(db, "1", "Lovely flat with a private garden and patio. Close to the common.", rent="2400")
    add(db, "2", "Modern flat near the station, no outside space.", rent="1800")
    both = add(db, "3", "Garden flat, a garden and another garden for the keen gardener.", rent="2600")
    hits = search_descriptions(db, "garden")
    assert {h["property_id"] for h in hits} == {garden, both}
    assert hits[0]["property_id"] == both                                        # more mentions rank first
    assert "[garden]" in hits[0]["excerpt"] and hits[0]["rent_pcm"] == 2600.0 and hits[0]["url"]
    assert search_descriptions(db, '"private garden"')[0]["property_id"] == garden           # phrase
    assert [h["property_id"] for h in search_descriptions(db, "garden -patio")] == [both]    # exclusion
    assert search_descriptions(db, "swimming pool") == []
    assert search_descriptions(db, "garden", limit=1)[:1] and len(search_descriptions(db, "garden", limit=1)) == 1


def test_search_ignores_withdrawn_and_filtered_listings(db: Database) -> None:
    pid = add(db, "1", "A garden flat.")
    assert [h["property_id"] for h in search_descriptions(db, "garden")] == [pid]
    db.execute("UPDATE listings SET status = 'withdrawn'")
    assert search_descriptions(db, "garden") == []


def test_search_tool_returns_json_and_survives_odd_input(db: Database) -> None:
    add(db, "1", "A garden flat.")
    t = tools(db)["search_descriptions"]
    out = json.loads(t.invoke({"query": "garden"}))                              # type: ignore[attr-defined]
    assert out[0]["address"] == "1 Road"
    assert isinstance(t.invoke({"query": '"unbalanced'}), str)                    # type: ignore[attr-defined]


def test_query_tool_returns_rows_and_errors_back_to_the_model(db: Database) -> None:
    add(db, "1", "A flat.", rent="1700")
    reset_sql_errors()
    q = tools(db)["query_sql"]
    ok = json.loads(q.invoke({"sql": "SELECT rent_pcm FROM v_properties"}))       # type: ignore[attr-defined]
    assert ok["columns"] == ["rent_pcm"] and ok["rows"] == [[1700.0]] and ok["total_rows"] == 1 and ok["truncated"] is False
    err = q.invoke({"sql": "SELECT * FROM listings"})                             # type: ignore[attr-defined]
    assert err.startswith("SQL error:") and "not available" in err


def test_query_tool_stops_the_model_retrying_forever(db: Database) -> None:
    reset_sql_errors()
    q = tools(db)["query_sql"]
    for _ in range(MAX_SQL_ERRORS):
        assert q.invoke({"sql": "DROP TABLE listings"}).startswith("SQL error")   # type: ignore[attr-defined]
    assert "Stop retrying" in q.invoke({"sql": "SELECT 1"})                       # type: ignore[attr-defined]
    reset_sql_errors()
    assert q.invoke({"sql": "SELECT 1"}).startswith("{")                          # type: ignore[attr-defined]


def test_query_tool_limits_rows_shown_to_the_model(db: Database) -> None:
    for i in range(30):
        add(db, str(i), f"Flat number {i}.", address=f"{i} Unique Street")
    reset_sql_errors()
    out = json.loads(tools(db)["query_sql"].invoke({"sql": "SELECT id FROM v_properties"}))   # type: ignore[attr-defined]
    assert out["total_rows"] == 30 and out["shown"] == 25 and len(out["rows"]) == 25


def test_schema_tool_returns_the_context(db: Database) -> None:
    assert "VIEW v_properties" in tools(db)["get_schema"].invoke({})                # type: ignore[attr-defined]
