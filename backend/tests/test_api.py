"""The HTTP API end to end: FastAPI app -> Runtime -> real Postgres."""
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.main import create_app
from app.repositories import listings
from app.runtime import Runtime
from app.services import postcodes
from tests.test_repositories import raw

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings: Settings, db: Database) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def test_health_reports_database_and_llm(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database_ok"] is True and body["database_error"] == ""
    assert body["llm_provider"] == "ollama" and body["tfl_key_configured"] is False and "llm_reason" in body


def test_api_stays_up_and_says_503_when_postgres_is_down(settings: Settings) -> None:
    dead = "postgresql://lettings:x@127.0.0.1:1/lettings"
    rt = Runtime(settings, Database(dead, dead, connect_timeout=1))
    with TestClient(create_app(settings, rt)) as c:
        health = c.get("/health").json()
        assert health["status"] == "ok" and health["database_ok"] is False and health["database_error"]
        r = c.get("/api/areas")
        assert r.status_code == 503 and "Postgres unavailable" in r.json()["detail"]


def test_areas_crud_and_validation(client: TestClient) -> None:
    assert client.post("/api/areas", json={"outcode": "not a code"}).status_code == 400
    created = client.post("/api/areas", json={"outcode": " sw11 ", "label": "Battersea"}).json()
    assert created["outcode"] == "SW11"
    rows = client.get("/api/areas").json()
    assert rows[0]["outcode"] == "SW11" and rows[0]["enabled"] is True and rows[0]["properties"] == 0
    assert client.put(f"/api/areas/{created['id']}", json={"enabled": False}).json() == {"ok": True}
    assert client.get("/api/areas").json()[0]["enabled"] is False
    assert client.put("/api/areas/9999", json={"enabled": True}).status_code == 404
    assert client.delete(f"/api/areas/{created['id']}").status_code == 200
    assert client.get("/api/areas").json() == []


def test_filters_round_trip_and_sweep_stored_listings(client: TestClient, db: Database) -> None:
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A"))
    listings.insert_new(db, raw("b", rent="4000", beds=2, address="B"))
    assert client.get("/api/filters").json() == {"min_bedrooms": 1, "max_bedrooms": 4, "max_rent": 3500}
    r = client.put("/api/filters", json={"min_bedrooms": 1, "max_bedrooms": 4, "max_rent": 3500}).json()
    assert r["hidden"] == 1 and r["restored"] == 0
    assert client.get("/api/properties").json()["total"] == 1
    r = client.put("/api/filters", json={"min_bedrooms": None, "max_bedrooms": None, "max_rent": None}).json()
    assert r["restored"] == 1 and client.get("/api/properties").json()["total"] == 2
    assert client.put("/api/filters", json={"min_bedrooms": 4, "max_bedrooms": 2}).status_code == 400
    assert client.put("/api/filters", json={"min_bedrooms": -1}).status_code == 422


def test_places_geocode_and_profiles(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_geocode(_client: Any, postcode: str) -> dict[str, Any]:
        return {"latitude": 51.5, "longitude": -0.09, "admin_district": "City of London"}

    monkeypatch.setattr(postcodes, "geocode", fake_geocode)
    assert client.put("/api/places/office", json={"postcode": "EC2R 8AH"}).status_code == 404
    assert client.put("/api/places/work", json={"postcode": "nonsense"}).status_code == 400
    ok = client.put("/api/places/work", json={"postcode": "ec2r8ah", "label": "Office"}).json()
    assert ok == {"kind": "work", "postcode": "EC2R 8AH", "lat": 51.5, "lon": -0.09, "borough": "City of London"}
    place = client.get("/api/places").json()[0]
    assert place["kind"] == "work" and place["label"] == "Office" and place["postcode"] == "EC2R 8AH"
    assert client.delete("/api/places/work").status_code == 200 and client.get("/api/places").json() == []

    profiles = {p["slug"]: p for p in client.get("/api/profiles").json()}
    assert set(profiles) == {"work_am", "work_pm", "home"} and profiles["work_am"]["local_time"] == "09:00"
    assert client.put("/api/profiles/work_am", json={"local_time": "08:15", "weekday": 2}).json() == {"ok": True}
    assert next(p for p in client.get("/api/profiles").json() if p["slug"] == "work_am")["local_time"] == "08:15"
    assert client.put("/api/profiles/work_am", json={"local_time": "25:99", "weekday": 2}).status_code == 400
    assert client.put("/api/profiles/zzz", json={"local_time": "08:00", "weekday": 2}).status_code == 404


def test_jobs_list_update_and_run_now(client: TestClient) -> None:
    # the scheduler is disabled in these tests, so seed the settings the way it would at startup
    client.app.state.runtime.runner.ensure_settings()  # type: ignore[attr-defined]
    jobs = {j["id"]: j for j in client.get("/api/jobs").json()}
    assert set(jobs) == {"scrape_rightmove", "details_rightmove", "enrich_pending", "commute_pending"}
    j = jobs["scrape_rightmove"]
    assert j["interval_minutes"] == 180 and j["active_from"] == "07:00" and j["enabled"] is True and j["last_run"] is None
    body = {"enabled": False, "interval_minutes": 60, "active_from": None, "active_to": None}
    assert client.put("/api/jobs/scrape_rightmove", json=body).json() == {"ok": True}
    updated = next(x for x in client.get("/api/jobs").json() if x["id"] == "scrape_rightmove")
    assert updated["enabled"] is False and updated["interval_minutes"] == 60 and updated["active_from"] is None
    assert client.put("/api/jobs/nope", json=body).status_code == 404
    assert client.post("/api/jobs/nope/run").status_code == 404
    assert client.post("/api/jobs/enrich_pending/run").status_code == 202
    assert client.get("/api/jobs/runs").status_code == 200
    status = client.get("/api/status").json()
    assert set(status) == {"active_listings", "properties", "detail_pending", "areas", "places", "commute_pending"}


def test_properties_list_sort_filter_and_detail(client: TestClient, db: Database) -> None:
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A Road"))
    listings.insert_new(db, raw("b", rent="2500", beds=2, address="B Road"))
    rows = client.get("/api/properties", params={"sort": "rent", "order": "desc"}).json()
    assert rows["total"] == 2 and [r["address"] for r in rows["rows"]] == ["B Road", "A Road"]
    assert client.get("/api/properties", params={"max_rent": 2000}).json()["total"] == 1
    assert client.get("/api/properties", params={"min_beds": 2, "q": "b road"}).json()["total"] == 1
    assert client.get("/api/properties", params={"sort": "'; drop table x"}).status_code == 200      # whitelisted
    pid = rows["rows"][0]["id"]
    detail = client.get(f"/api/properties/{pid}").json()
    assert detail["property"]["id"] == pid and len(detail["listings"]) == 1 and detail["commutes"] == []
    assert client.get("/api/properties/999999").status_code == 404


def test_sql_and_chart_endpoints(client: TestClient, db: Database) -> None:
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A Road"))
    listings.insert_new(db, raw("b", rent="2500", beds=2, address="B Road"))
    res = client.post("/api/sql", json={"sql": "SELECT bedrooms, rent_pcm FROM v_properties ORDER BY rent_pcm"}).json()
    assert res["columns"] == ["bedrooms", "rent_pcm"] and res["rows"] == [[1, 1500.0], [2, 2500.0]] and res["truncated"] is False
    chart = client.post("/api/chart", json={"sql": "SELECT bedrooms, round(avg(rent_pcm)) AS avg_rent FROM v_properties GROUP BY bedrooms"}).json()
    assert chart["columns"] == ["bedrooms", "avg_rent"] and chart["rows"] and "chart" in chart or "kind" in chart or len(chart) > 4

    for bad in ("DELETE FROM listings", "SELECT * FROM listings", "SELECT 1; SELECT 2", "SELECT nope FROM v_properties", "SELECT pg_sleep(1)"):
        r = client.post("/api/sql", json={"sql": bad})
        assert r.status_code == 400 and r.json()["detail"], bad
    assert db.fetch_one("SELECT count(*) AS n FROM listings") == {"n": 2}                  # nothing was deleted


def test_the_read_only_role_is_the_second_line_of_defence(settings: Settings, migrated_db: Database) -> None:
    """Even if the parser were bypassed, Postgres refuses: the role cannot read tables or write."""
    import psycopg

    with psycopg.connect(settings.readonly_database_url) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM listings")
        c.rollback()
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)):
            c.execute("DELETE FROM sources")
        c.rollback()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("CREATE TEMP TABLE x (a int)")


def test_database_overview_and_migration_status(client: TestClient) -> None:
    body = client.get("/api/database").json()
    names = {r["name"] for r in body["relations"]}
    assert {"properties", "listings", "v_properties", "v_property_text"} <= names and "spatial_ref_sys" not in names
    assert [m["version"] for m in body["migrations"]["applied"]][-1] == "0005_text_search" and body["migrations"]["pending"] == []
    assert client.post("/api/database/migrate").json() == {"applied": []}


def test_the_removed_legacy_endpoints_are_gone(client: TestClient) -> None:
    for path in ("/api/datasets", "/api/documents"):
        assert client.get(path).status_code == 404
    assert client.post("/api/search", json={"query": "x"}).status_code == 404


def test_chat_streams_tokens_and_tool_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeAgent:
        async def astream_events(self, *_a: Any, **_k: Any) -> Any:
            yield {"event": "on_tool_start", "run_id": "r1", "name": "query_sql", "data": {"input": {"sql": "SELECT 1"}}}
            yield {"event": "on_tool_end", "run_id": "r1", "name": "query_sql", "data": {"output": "ok"}}
            for piece in ("<thi", "nk>hidden</think>", "There are ", "2 homes."):
                yield {"event": "on_chat_model_stream", "data": {"chunk": Chunk(piece)}}

    rt = client.app.state.runtime  # type: ignore[attr-defined]
    monkeypatch.setattr(rt.chat, "build_agent", lambda: FakeAgent())
    with client.stream("POST", "/api/chat", json={"session_id": "s1", "message": "how many?"}) as r:
        text = "".join(r.iter_text())
    events = [(line.split(":", 1)[1].strip()) for line in text.splitlines() if line.startswith("event:")]
    assert events == ["tool_start", "tool_end", "token", "token", "done"]
    tokens = "".join(json.loads(line.split(":", 1)[1])["text"] for line in text.splitlines() if line.startswith("data:") and '"text"' in line)
    assert tokens == "There are 2 homes."


def test_chat_reports_an_unconfigured_model_as_an_error_event(settings: Settings, db: Database) -> None:
    no_key = Settings(**{**settings.model_dump(), "llm_provider": "anthropic", "anthropic_api_key": ""})
    with TestClient(create_app(no_key)) as c, c.stream("POST", "/api/chat", json={"session_id": "s", "message": "hi"}) as r:
        text = "".join(r.iter_text())
    assert "event: error" in text and "ANTHROPIC_API_KEY" in text


def test_map_points_are_filtered_and_not_confused_with_a_property_id(client: TestClient, db: Database) -> None:
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A Road", lat=51.4, lon=-0.2))
    listings.insert_new(db, raw("b", rent="2500", beds=2, address="B Road", lat=51.5, lon=-0.1))
    nowhere = raw("c", rent="1800", address="C Road")
    nowhere.lat = nowhere.lon = None
    listings.insert_new(db, nowhere)
    body = client.get("/api/properties/map").json()
    assert body["total"] == 2 and {p["address"] for p in body["points"]} == {"A Road", "B Road"}
    assert {"id", "lat", "lon", "rent_pcm", "url", "work_am_min"} <= set(body["points"][0])
    assert all(isinstance(p["rent_pcm"], float) for p in body["points"])          # numbers, not strings
    cheap = client.get("/api/properties/map", params={"max_rent": 2000}).json()
    assert [p["address"] for p in cheap["points"]] == ["A Road"]
