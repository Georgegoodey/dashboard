"""Key information read from the stored adverts: furnishing, shared, pets, bills, garden, parking, balcony."""
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.main import create_app
from app.repositories import commutes, listings, properties
from tests.test_repositories import raw

pytestmark = pytest.mark.integration


def info(db: Database, furnished: str | None = None, description: str | None = None, features: list[str] | None = None) -> dict[str, Any]:
    row = db.fetch_one("SELECT listing_key_info(%s, %s, %s::jsonb) AS k", (furnished, description, json.dumps(features or [])))
    assert row is not None
    return dict(row["k"])


@pytest.mark.parametrize("furnished, expected", [
    ("Furnished", "furnished"), ("Unfurnished", "unfurnished"), ("Part furnished", "part_furnished"), ("Part Furnished", "part_furnished"),
    ("Furnished or unfurnished, landlord is flexible", "flexible"), ("At tenant choice", "flexible"),
    ("Available as furnished or unfurnished", "flexible"), (None, None), ("", None),
])
def test_the_furnishing_field_in_all_its_wordings(db: Database, furnished: str | None, expected: str | None) -> None:
    assert info(db, furnished)["furnish"] == expected


@pytest.mark.parametrize("text, expected", [
    ("Offered unfurnished.", "unfurnished"), ("A well presented FURNISHED flat", "furnished"), ("part-furnished with a sofa", "part_furnished"),
    ("Available furnished or unfurnished", "flexible"), ("Furnished/unfurnished by arrangement", "flexible"), ("Bright and airy flat", None),
])
def test_furnishing_is_read_from_the_text_when_the_field_is_empty(db: Database, text: str, expected: str | None) -> None:
    assert info(db, None, text)["furnish"] == expected
    assert info(db, None, None, [text])["furnish"] == expected               # also from the bullet points


def test_the_field_beats_the_text(db: Database) -> None:
    assert info(db, "Unfurnished", "Lovely furnished kitchen")["furnish"] == "unfurnished"


@pytest.mark.parametrize("tag, yes, no", [
    ("pets", ["Pets considered", "pet friendly building", "Pets allowed"], ["No pets", "Pets are not allowed", "A lovely flat"]),
    ("bills", ["All bills included", "Rent is inclusive of bills", "Bills Included"], ["Bills not included", "A lovely flat"]),
    ("garden", ["Private garden", "Communal gardens"], ["No garden", "A lovely flat"]),
    ("parking", ["Off street parking", "Garage", "driveway for two cars"], ["No parking", "A lovely flat"]),
    ("balcony", ["Private balcony", "Roof terrace", "Balconies"], ["A lovely flat"]),
    ("shared", ["House share", "A shared flat", "Room available in a flat", "Room in a shared house"],
     ["A lovely flat", "Sharing a roof terrace", "Ideal for sharers", "Ideal for a professional sharer"]),
])
def test_each_tag_is_found_and_not_found(db: Database, tag: str, yes: list[str], no: list[str]) -> None:
    for text in yes:
        assert info(db, None, text)[tag] is True, text
        assert info(db, None, None, [text])[tag] is True, text
    for text in no:
        assert info(db, None, text)[tag] is False, text


def test_the_key_info_follows_the_advert_when_its_details_arrive(db: Database) -> None:
    lid, _ = listings.insert_new(db, raw("1"))
    assert db.fetch_one("SELECT key_info ->> 'furnish' AS f FROM listings WHERE id = %s", (lid,)) == {"f": None}
    item = raw("1")
    item.furnished, item.description, item.key_features, item.has_detail = "Part furnished", "Pets allowed. Garden.", ["Balcony"], True
    listings.save_detail(db, lid, item)
    k = db.fetch_one("SELECT key_info AS k FROM listings WHERE id = %s", (lid,))
    assert k is not None and k["k"]["furnish"] == "part_furnished" and k["k"]["pets"] and k["k"]["garden"] and k["k"]["balcony"]


# ── in the view and the filters ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(settings: Settings, db: Database) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def seed(db: Database) -> dict[str, int]:
    """Four homes: furnished with pets and a garden, unfurnished with parking, flexible, and one that says nothing."""
    rows = {"a": ("Furnished", "Pets allowed. Large garden.", []), "b": ("Unfurnished", "Off street parking.", ["Bills included"]),
            "c": ("Furnished or unfurnished, landlord is flexible", "Roof terrace.", []), "d": (None, "A flat.", [])}
    ids = {}
    for i, (name, (furnished, text, feats)) in enumerate(rows.items()):
        item = raw(name, rent=str(1500 + 500 * i), address=f"{name} Road")
        item.furnished, item.description, item.key_features = furnished, text, feats
        ids[name] = listings.insert_new(db, item)[1]
    return ids


def test_the_view_carries_the_key_info(db: Database) -> None:
    ids = seed(db)
    rows = {r["id"]: r for r in db.fetch_all("SELECT * FROM v_properties")}
    a, b, c, d = (rows[ids[k]] for k in "abcd")
    assert (a["furnish_type"], a["pets_allowed"], a["has_garden"], a["has_parking"]) == ("furnished", True, True, False)
    assert (b["furnish_type"], b["has_parking"], b["bills_included"], b["pets_allowed"]) == ("unfurnished", True, True, False)
    assert (c["furnish_type"], c["has_balcony"]) == ("flexible", True) and d["furnish_type"] is None
    assert not any(r["is_shared"] for r in rows.values())


def test_a_room_share_property_type_is_shared(db: Database) -> None:
    item = raw("s")
    item.property_type = "House share"
    listings.insert_new(db, item)
    assert db.fetch_one("SELECT is_shared FROM v_properties") == {"is_shared": True}


def test_filter_by_furnishing_and_features(client: TestClient, db: Database) -> None:
    ids = seed(db)

    def found(**params: Any) -> set[int]:
        res = client.get("/api/properties", params=params)
        assert res.status_code == 200
        return {r["id"] for r in res.json()["rows"]}

    assert found() == set(ids.values())
    assert found(furnish="furnished") == {ids["a"], ids["c"]}                       # the flexible home suits either choice
    assert found(furnish="unfurnished") == {ids["b"], ids["c"]}
    assert found(furnish=["furnished", "unfurnished"]) == {ids["a"], ids["b"], ids["c"]}
    assert found(furnish="part_furnished") == {ids["c"]}
    assert found(has="pets") == {ids["a"]}
    assert found(has=["pets", "garden"]) == {ids["a"]} and found(has=["pets", "parking"]) == set()
    assert found(has="bills", furnish="unfurnished") == {ids["b"]}
    assert found(min_rent=2000, max_rent=2500) == {ids["c"], ids["b"]} and found(min_rent=1700) == {ids["b"], ids["c"], ids["d"]}
    assert client.get("/api/properties", params={"furnish": "bare"}).status_code == 400
    assert client.get("/api/properties", params={"has": "jacuzzi"}).status_code == 400

    points = client.get("/api/properties/map", params={"furnish": "furnished", "has": "pets"}).json()["points"]
    assert [p["id"] for p in points] == [ids["a"]] and points[0]["furnish_type"] == "furnished"
    assert client.get("/api/properties/map", params={"has": "jacuzzi"}).status_code == 400


def test_the_detail_carries_the_journey_times_and_key_info(client: TestClient, db: Database) -> None:
    ids = seed(db)
    db.execute("INSERT INTO commute_points (label, postcode, geom) VALUES ('Work', 'EC2R 8AH', ST_SetSRID(ST_MakePoint(-0.09, 51.5), 4326)::geography)")
    db.execute("INSERT INTO commute_profiles (point_id, direction, anchor, local_time, weekday) VALUES (1, 'to_place', 'arrive_by', '09:00', 1)")
    profile = db.fetch_one("SELECT id FROM commute_profiles")
    assert profile
    from datetime import date

    commutes.save_route(db, {"property_id": ids["a"], "profile_id": profile["id"]}, date(2026, 10, 20),
                        {"duration_min": 31, "summary": "Walk to X (5m) > 37 bus to Y (20m)", "start": "2026-10-20T08:15:00",
                         "arrival": "2026-10-20T08:46:00"})
    body = client.get(f"/api/properties/{ids['a']}").json()
    route = body["commutes"][0]
    assert route["departs"] == "2026-10-20T08:15:00" and route["arrives"] == "2026-10-20T08:46:00"
    assert route["summary"].startswith("Walk to X") and body["property"]["furnish_type"] == "furnished" and body["property"]["pets_allowed"]
    assert properties.detail(db, ids["a"]) is not None


def test_agent_schema_documents_the_new_columns(db: Database) -> None:
    from app.rag.schema import SchemaContext

    seed(db)
    text = SchemaContext(db).text()
    assert "furnish_type" in text and "pets_allowed" in text and "unfurnished" in text
