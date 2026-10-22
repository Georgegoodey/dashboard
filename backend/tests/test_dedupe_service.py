"""Merging the same home advertised on several portals: the planner (pure), the merge, the job and the API."""
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.jobs import tasks
from app.main import create_app
from app.repositories import commutes, listings
from app.runtime import Runtime
from app.services import dedupe
from app.services.dedupe import Edge, plan_from_edges, street_of
from app.sources.base import RawListing
from tests.test_repositories import raw


@pytest.fixture
def client(settings: Settings, db: Database) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


# ── the planner (no database) ───────────────────────────────────────────────────────────────────────────────────

def edge(a: int, b: int, sa: str = "rightmove", sb: str = "onthemarket", rent_diff: float = 0.0,
         addr_a: str = "wilton rd london sw19", addr_b: str = "wilton rd sw19") -> Edge:
    return Edge(a, b, frozenset({sa}), frozenset({sb}), 5.0, rent_diff, addr_a, addr_b)


@pytest.mark.parametrize("address, street", [
    ("wilton rd london sw19", "wilton"), ("12 wilton rd", "wilton"), ("flat b wilton rd", "wilton"),
    ("flat 3 12a embassy blvd", "embassy"), ("12 3", ""), ("", ""), ("the ave surbiton", "the"),
])
def test_the_street_is_the_first_word_after_any_flat_or_house_number(address: str, street: str) -> None:
    assert street_of(address) == street


def test_a_pair_on_two_portals_is_one_group() -> None:
    plan = plan_from_edges([edge(1, 2)])
    assert plan.clusters == [[1, 2]] and plan.absorbed == 1 and plan.by_sources == {"onthemarket + rightmove": 1}


def test_a_home_on_three_portals_is_one_group_when_every_pair_matches() -> None:
    plan = plan_from_edges([edge(1, 2, "rightmove", "onthemarket"), edge(1, 3, "rightmove", "openrent"),
                            edge(2, 3, "onthemarket", "openrent")])
    assert plan.clusters == [[1, 2, 3]] and plan.absorbed == 2 and plan.by_sources == {"onthemarket + openrent + rightmove": 1}


def test_a_chain_where_the_ends_do_not_match_is_left_alone() -> None:
    plan = plan_from_edges([edge(1, 2, "rightmove", "onthemarket"), edge(2, 3, "onthemarket", "openrent")])
    assert plan.clusters == [] and plan.incomplete_groups == 1


def test_a_home_with_two_candidates_on_one_portal_is_ambiguous_and_skipped_with_all_its_candidates() -> None:
    plan = plan_from_edges([edge(1, 2), edge(1, 3), edge(4, 5)])               # 1 matches two onthemarket homes; 4-5 is clean
    assert plan.clusters == [[4, 5]] and plan.ambiguous == 1


def test_the_ambiguity_check_counts_candidates_that_fail_the_street_check() -> None:
    plan = plan_from_edges([edge(1, 2), edge(1, 3, addr_b="hogarth rd sw5")])   # a second, different-street candidate
    assert plan.clusters == [] and plan.ambiguous == 1


def test_pairs_on_different_streets_or_with_any_difference_in_rent_are_not_merged() -> None:
    plan = plan_from_edges([edge(1, 2, addr_b="hogarth rd sw5"), edge(3, 4, rent_diff=0.025), edge(5, 6, rent_diff=0.002),
                            edge(7, 8, addr_a="", addr_b="")])
    assert plan.clusters == [] and plan.different_street == 2 and plan.rent_too_far == 2


# ── merging, against a database ─────────────────────────────────────────────────────────────────────────────────

def home(source: str, listing_id: str, address: str, rent: str = "2000", beds: int = 2, postcode: str | None = None,
         lat: float = 51.4700, lon: float = -0.1600) -> RawListing:
    item = raw(listing_id, rent=rent, beds=beds, address=address, lat=lat, lon=lon)
    item.source, item.postcode = source, postcode          # no postcode: as in a search result, so nothing matches on insert
    item.outcode = "SW11"
    return item


def property_count(db: Database) -> int:
    row = db.fetch_one("SELECT count(*) AS n FROM properties")
    assert row is not None
    return int(row["n"])


def test_the_same_home_from_two_portals_is_merged_into_one_property(db: Database) -> None:
    _, rm = listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, London, SW11", postcode="SW11 3GQ"))
    _, otm = listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, Battersea, London SW11", lat=51.47005, lon=-0.16005))
    assert property_count(db) == 2 and rm != otm

    result = dedupe.apply(db)

    assert result == {"groups": 1, "absorbed": 1, "listings_moved": 1}
    assert property_count(db) == 1
    survivor = db.fetch_one("SELECT id, postcode FROM properties")
    assert survivor == {"id": rm, "postcode": "SW11 3GQ"}                                  # the one with a postcode survives
    assert db.fetch_one("SELECT count(DISTINCT source_id) AS n, count(DISTINCT property_id) AS p FROM listings") == {"n": 2, "p": 1}
    audit = db.fetch_one("SELECT survivor_id, jsonb_array_length(absorbed) AS n, absorbed -> 0 -> 'property' ->> 'id' AS gone FROM property_merges")
    assert audit == {"survivor_id": rm, "n": 1, "gone": str(otm)}
    assert dedupe.merged_total(db) == 1
    assert dedupe.apply(db) == {"groups": 0, "absorbed": 0, "listings_moved": 0}            # nothing left to do


def test_the_view_then_shows_one_home_with_both_portals(db: Database) -> None:
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11", rent="2000"))
    listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, SW11", rent="2000"))
    dedupe.apply(db)
    rows = db.fetch_all("SELECT rent_pcm, sources FROM v_properties")
    assert len(rows) == 1 and rows[0]["sources"] == "onthemarket, rightmove" and int(rows[0]["rent_pcm"]) == 2000


def test_commute_routes_and_missing_details_follow_the_survivor(db: Database) -> None:
    _, a = listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    _, b = listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, SW11"))
    db.execute("UPDATE properties SET bathrooms = NULL WHERE id = %s", (a,))
    db.execute("UPDATE properties SET borough = 'Wandsworth', bathrooms = 2 WHERE id = %s", (b,))
    db.execute("INSERT INTO commute_points (label, postcode, geom) VALUES ('Work', 'EC2R 8AH', "
               "ST_SetSRID(ST_MakePoint(-0.09, 51.5), 4326)::geography)")
    db.execute("INSERT INTO commute_profiles (point_id, direction, anchor, local_time, weekday) VALUES (1, 'to_place', 'arrive_by', '09:00', 1)")
    profile = db.fetch_one("SELECT id FROM commute_profiles")
    assert profile
    commutes.save_route(db, {"property_id": b, "profile_id": profile["id"]}, date(2026, 10, 20), {"duration_min": 30})

    dedupe.apply(db)

    row = db.fetch_one("SELECT id, borough, bathrooms FROM properties")
    assert row == {"id": a, "borough": "Wandsworth", "bathrooms": 2}                          # gaps filled from the absorbed home
    assert db.fetch_one("SELECT property_id FROM commute_routes") == {"property_id": a}      # the route was kept, not recomputed


@pytest.mark.parametrize("other", [
    {"beds": 3},                                                  # a different number of bedrooms
    {"rent": "2100"},                                             # 5% apart
    {"rent": "2001"},                                             # a pound apart: not identical
    {"lat": 51.4710, "lon": -0.1600},                             # about 110 m away
    {"address": "Hogarth Road, SW11"},                            # a different street
])
def test_homes_that_differ_are_not_merged(db: Database, other: dict[str, Any]) -> None:
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    kw: dict[str, Any] = {"address": "Wilton Rd, SW11", **other}
    listings.insert_new(db, home("onthemarket", "otm1", **kw))
    assert dedupe.plan(db).clusters == [] and dedupe.apply(db)["absorbed"] == 0 and property_count(db) == 2


def test_two_adverts_from_one_portal_are_never_merged(db: Database) -> None:
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    listings.insert_new(db, home("rightmove", "rm2", "Wilton Road, SW11"))
    assert dedupe.plan(db).edges == 0 and property_count(db) == 2


def test_identical_flats_in_one_block_are_ambiguous_and_left_alone(db: Database) -> None:
    for i in (1, 2):
        listings.insert_new(db, home("rightmove", f"rm{i}", "Tower House, Wilton Road, SW11"))
        listings.insert_new(db, home("onthemarket", f"otm{i}", "Tower House, Wilton Rd, SW11"))
    plan = dedupe.plan(db)
    assert plan.clusters == [] and plan.ambiguous == 4 and dedupe.apply(db)["absorbed"] == 0 and property_count(db) == 4


def test_three_portals_become_one_property(db: Database) -> None:
    for source, lid, addr in (("rightmove", "rm1", "Wilton Road, SW11"), ("onthemarket", "otm1", "Wilton Rd, London SW11"),
                              ("openrent", "or1", "Wilton Road, SW11")):
        listings.insert_new(db, home(source, lid, addr))
    assert dedupe.apply(db) == {"groups": 1, "absorbed": 2, "listings_moved": 2} and property_count(db) == 1


def test_withdrawn_adverts_do_not_trigger_a_merge(db: Database) -> None:
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, SW11"))
    db.execute("UPDATE listings SET status = 'withdrawn' WHERE source_listing_id = 'otm1'")
    assert dedupe.plan(db).clusters == []


def test_describe_lists_the_homes_in_each_group(db: Database) -> None:
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, SW11"))
    found = dedupe.plan(db)
    [group] = dedupe.describe(db, found.clusters)
    assert [h["adverts"][0]["source"] for h in group["homes"]] == ["rightmove", "onthemarket"]
    assert [h["adverts"][0]["rent_pcm"] for h in group["homes"]] == [2000.0, 2000.0]


# ── the job and the API ─────────────────────────────────────────────────────────────────────────────────────────

def seed_pair(db: Database) -> None:
    dedupe.set_auto(db, False)                                 # settings outlive the data a test starts from
    listings.insert_new(db, home("rightmove", "rm1", "Wilton Road, SW11"))
    listings.insert_new(db, home("onthemarket", "otm1", "Wilton Rd, SW11"))


@pytest.mark.integration
async def test_the_job_only_reports_until_automatic_merging_is_on(settings: Settings, db: Database) -> None:
    seed_pair(db)
    rt = Runtime(settings, db)
    stats = await tasks.dedupe_properties(rt)
    assert stats["groups"] == 1 and stats["would_absorb"] == 1 and "dry run" in stats["note"] and property_count(db) == 2

    dedupe.set_auto(db, True)
    stats = await tasks.dedupe_properties(rt)
    assert stats["absorbed"] == 1 and stats["rows_updated"] == 1 and property_count(db) == 1
    dedupe.set_auto(db, False)


def test_the_api_previews_switches_and_applies(client: TestClient, db: Database) -> None:
    seed_pair(db)
    body = client.get("/api/dedupe").json()
    assert body["auto"] is False and body["merged_total"] == 0
    assert body["preview"]["groups"] == 1 and body["preview"]["would_absorb"] == 1
    assert [h["adverts"][0]["source"] for h in body["samples"][0]["homes"]] == ["rightmove", "onthemarket"]
    assert property_count(db) == 2                                                          # looking changed nothing

    assert client.put("/api/dedupe", json={"auto": True}).json() == {"auto": True}
    assert client.get("/api/dedupe").json()["auto"] is True
    assert client.post("/api/dedupe/apply").json() == {"groups": 1, "absorbed": 1, "listings_moved": 1}
    client.put("/api/dedupe", json={"auto": False})
    again = client.get("/api/dedupe").json()
    assert property_count(db) == 1 and again["merged_total"] == 1 and again["preview"]["groups"] == 0
    assert client.get("/api/properties").json()["total"] == 1
