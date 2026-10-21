"""Ingest SQL against a real database: inserts, matching, price history, withdrawal, filters, commutes."""
from datetime import date
from decimal import Decimal

import pytest

from app.db.database import Database
from app.repositories import areas, commute_points, commutes, jobs, listings, properties
from app.services import filters
from app.sources.base import RawListing, SearchFilters

pytestmark = pytest.mark.integration


def raw(listing_id: str, rent: str = "2000", beds: int = 2, postcode: str = "SW11 7FD", address: str = "1 Test Street, London",
        lat: float = 51.47, lon: float = -0.16, **kw: object) -> RawListing:
    return RawListing(source="rightmove", source_listing_id=listing_id, url=f"https://example.test/{listing_id}", address=address,
                      postcode=postcode, outcode=postcode.split()[0], lat=lat, lon=lon, bedrooms=beds, bathrooms=1,
                      property_type="Flat", rent_pcm=Decimal(rent), rent_pw=None, **kw)  # type: ignore[arg-type]


def test_insert_new_creates_property_listing_and_first_price_row(db: Database) -> None:
    listing_id, property_id = listings.insert_new(db, raw("100"))
    assert listing_id and property_id
    assert db.fetch_one("SELECT count(*) AS n FROM listing_price_history WHERE listing_id = %s", (listing_id,)) == {"n": 1}
    row = db.fetch_one("SELECT outcode, bedrooms, ST_Y(geom::geometry) AS lat FROM properties WHERE id = %s", (property_id,))
    assert row and row["outcode"] == "SW11" and row["bedrooms"] == 2 and round(row["lat"], 2) == 51.47


def test_same_portal_adverts_at_one_address_are_never_merged(db: Database) -> None:
    _, p1 = listings.insert_new(db, raw("1"))
    _, p2 = listings.insert_new(db, raw("2"))             # same postcode, address and bedrooms
    assert p1 != p2


def test_another_portal_matches_the_existing_property(db: Database) -> None:
    _, p1 = listings.insert_new(db, raw("1"))
    other = raw("zz-9")
    other.source = "openrent"
    _, p2 = listings.insert_new(db, other)
    assert p1 == p2


def test_touch_known_records_a_price_change_and_revives(db: Database) -> None:
    listing_id, _ = listings.insert_new(db, raw("1", rent="2000"))
    db.execute("UPDATE listings SET status = 'withdrawn' WHERE id = %s", (listing_id,))
    result = listings.touch_known(db, "rightmove", [raw("1", rent="1900")])
    assert result == {"touched": 1, "repriced": 1, "revived": 1}
    row = db.fetch_one("SELECT status, rent_pcm FROM listings WHERE id = %s", (listing_id,))
    assert row == {"status": "active", "rent_pcm": Decimal("1900.00")}
    assert db.fetch_one("SELECT count(*) AS n FROM listing_price_history WHERE listing_id = %s", (listing_id,)) == {"n": 2}
    changes = db.fetch_all("SELECT prev_rent_pcm, new_rent_pcm, change_pct FROM v_price_changes")
    assert len(changes) == 1 and changes[0]["change_pct"] == Decimal("-5.0")


def test_known_listings_maps_by_source_id(db: Database) -> None:
    listings.insert_new(db, raw("7"))
    assert set(listings.known_listings(db, "rightmove", ["7", "8"])) == {"7"}
    assert listings.known_listings(db, "rightmove", []) == {}


def test_withdrawn_only_after_three_complete_scrapes_miss_it(db: Database) -> None:
    listings.insert_new(db, raw("keep"))
    gone_id, _ = listings.insert_new(db, raw("gone", address="2 Other Road"))
    for i in range(listings.WITHDRAW_AFTER_MISSED_SCRAPES):
        status = db.fetch_one("SELECT status FROM listings WHERE id = %s", (gone_id,))
        assert status == {"status": "active"}, f"withdrawn too early (miss {i})"
        withdrawn = listings.mark_missing(db, "rightmove", "SW11", {"keep"})
    assert withdrawn == 1
    assert db.fetch_one("SELECT status FROM listings WHERE id = %s", (gone_id,)) == {"status": "withdrawn"}
    assert db.fetch_one("SELECT count(*) AS n FROM listing_price_history WHERE listing_id = %s AND status = 'withdrawn'", (gone_id,)) == {"n": 1}
    assert listings.mark_missing(db, "rightmove", "SW11", {"keep"}) == 0           # not withdrawn twice
    assert db.fetch_one("SELECT count(*) AS n FROM listings WHERE source_listing_id = 'keep' AND status = 'active'") == {"n": 1}


def test_pending_details_and_save_detail_sharpen_the_property(db: Database) -> None:
    lid, pid = listings.insert_new(db, raw("5", postcode="SW11 2AA", lat=51.0, lon=-0.1))
    assert [r["id"] for r in listings.pending_details(db, "rightmove", 10)] == [lid]
    assert listings.count_pending_details(db, "rightmove") == 1
    detail = raw("5", postcode="SW11 7FD", lat=51.47, lon=-0.16, description="A bright flat with a private garden and balcony",
                 furnished="Furnished", deposit=Decimal("2300"), has_detail=True)
    detail.key_features = ["Garden", "Balcony"]
    listings.save_detail(db, lid, detail)
    assert listings.count_pending_details(db, "rightmove") == 0
    row = db.fetch_one("SELECT postcode, ST_Y(geom::geometry) AS lat FROM properties WHERE id = %s", (pid,))
    assert row and row["postcode"] == "SW11 7FD" and round(row["lat"], 2) == 51.47
    assert db.fetch_one("SELECT furnished, deposit FROM listings WHERE id = %s", (lid,)) == {"furnished": "Furnished", "deposit": Decimal("2300.00")}


def test_withdraw_marks_a_listing(db: Database) -> None:
    lid, _ = listings.insert_new(db, raw("9"))
    listings.withdraw(db, lid)
    assert db.fetch_one("SELECT status FROM listings WHERE id = %s", (lid,)) == {"status": "withdrawn"}


def test_filters_hide_and_restore_without_deleting(db: Database) -> None:
    areas.upsert(db, "SW11", "Battersea", True)
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A"))
    listings.insert_new(db, raw("b", rent="3000", beds=3, address="B"))
    listings.insert_new(db, raw("c", rent="5000", beds=2, address="C"))      # over the rent limit
    listings.insert_new(db, raw("d", rent="2000", beds=6, address="D"))      # too many bedrooms
    tight = SearchFilters(min_bedrooms=1, max_bedrooms=4, max_rent=3500)
    assert filters.update(db, tight) == {"hidden": 2, "restored": 0}
    counts = {r["status"]: r["n"] for r in db.fetch_all("SELECT status, count(*) AS n FROM listings GROUP BY status")}
    assert counts == {"active": 2, "filtered": 2}
    assert filters.load(db) == tight
    assert filters.update(db, SearchFilters(min_bedrooms=None, max_bedrooms=None, max_rent=None)) == {"hidden": 0, "restored": 2}


def test_filters_reject_an_impossible_range(db: Database) -> None:
    from app.core.errors import InvalidInput

    with pytest.raises(InvalidInput):
        filters.update(db, SearchFilters(min_bedrooms=3, max_bedrooms=1, max_rent=None))


def test_properties_view_search_and_detail(db: Database) -> None:
    listings.insert_new(db, raw("a", rent="1500", beds=1, address="A Road"))
    listings.insert_new(db, raw("b", rent="2500", beds=2, address="B Road"))
    res = properties.search(db, q=None, min_rent=None, max_rent=2000, min_beds=None, max_beds=None, borough=None, commute=[],
                            furnished=None, sort="rent", order="asc", limit=10, offset=0)
    assert res["total"] == 1 and res["rows"][0]["address"] == "A Road"
    pid = res["rows"][0]["id"]
    detail = properties.detail(db, pid)
    assert detail and detail["property"]["id"] == pid and len(detail["listings"]) == 1 and len(detail["price_history"]) == 1
    assert properties.detail(db, 999999) is None
    assert properties.counts(db)["active_listings"] == 2


def test_areas_crud(db: Database) -> None:
    area_id = areas.upsert(db, "SW11", "Battersea", True)
    assert areas.upsert(db, "SW11", "Battersea 2", False) == area_id                 # upsert on outcode
    assert [a["label"] for a in areas.list_all(db)] == ["Battersea 2"]
    assert areas.list_enabled(db) == []
    assert areas.update(db, area_id, None, True) and areas.update(db, 99999, None, True) is False
    areas.save_source_id(db, area_id, "rightmove", "OUTCODE^2497")
    assert areas.list_enabled(db)[0]["source_ids"] == {"rightmove": "OUTCODE^2497"}
    areas.delete(db, area_id)
    assert areas.list_all(db) == []


def _point(db: Database, label: str = "Work", pm: bool = True, lat: float = 51.5, lon: float = -0.09) -> tuple[int, list[int]]:
    journeys = [commute_points.TO_POINT, commute_points.FROM_POINT] if pm else [commute_points.TO_POINT]
    point_id = commute_points.add(db, label, None, "EC2R 8AH", lat, lon, journeys)
    ids = [r["id"] for r in db.fetch_all("SELECT id FROM commute_profiles WHERE point_id = %s ORDER BY id", (point_id,))]
    return point_id, ids


def _route(db: Database, pid: int, profile_id: int, minutes: int | None) -> None:
    commutes.save_route(db, {"property_id": pid, "profile_id": profile_id}, date(2026, 10, 20),
                        {"duration_min": minutes, "walk_min": 5, "transfers": 1, "fare_pence": 280, "summary": "x"} if minutes else None)


def test_points_and_journeys_invalidate_routes_only_when_the_plan_changes(db: Database) -> None:
    from datetime import time

    _, pid = listings.insert_new(db, raw("1"))
    point_id, (to_id, back_id) = _point(db)
    _route(db, pid, to_id, 31)
    assert db.fetch_one("SELECT duration_min, point_label FROM v_commutes WHERE property_id = %s", (pid,)) == {
        "duration_min": 31, "point_label": "Work"}
    assert commute_points.update_journey(db, to_id, "to_place", "arrive_by", time(9, 0), 1, False)       # only switched off
    assert db.fetch_one("SELECT count(*) AS n FROM commute_routes") == {"n": 1}
    assert db.fetch_one("SELECT count(*) AS n FROM v_commutes") == {"n": 0}                              # hidden while off
    assert commute_points.update_journey(db, to_id, "to_place", "arrive_by", time(8, 30), 2, True)
    assert db.fetch_one("SELECT count(*) AS n FROM commute_routes") == {"n": 0}                          # new time: recompute
    assert commute_points.update_journey(db, 999999, "to_place", "arrive_by", time(8, 0), 1, True) is False
    _route(db, pid, back_id, 25)
    assert commute_points.update(db, point_id, "Office", None, True, ("E14 5AB", 51.5, -0.02))
    assert db.fetch_one("SELECT count(*) AS n FROM commute_routes") == {"n": 0}                          # point moved


def test_a_deactivated_or_deleted_point_leaves_the_views_and_comes_back(db: Database) -> None:
    _, pid = listings.insert_new(db, raw("1"))
    point_id, (to_id, _) = _point(db)
    _route(db, pid, to_id, 31)
    assert commute_points.update(db, point_id, "Work", None, False)
    assert db.fetch_one("SELECT count(*) AS n FROM v_commutes") == {"n": 0}
    assert db.fetch_one("SELECT count(*) AS n FROM v_commute_points") == {"n": 0}
    assert commutes.count_pending(db) == 0                                                               # no TfL calls for it
    assert commute_points.update(db, point_id, "Work", None, True)
    assert db.fetch_one("SELECT count(*) AS n FROM v_commutes") == {"n": 1}                              # routes were kept
    assert commute_points.delete(db, point_id) and commute_points.delete(db, point_id) is False
    assert db.fetch_one("SELECT count(*) AS n FROM commute_routes") == {"n": 0}


def test_pending_commute_pairs_cover_every_active_point(db: Database) -> None:
    listings.insert_new(db, raw("1"))
    assert commutes.pending_pairs(db, 10) == [] and commutes.count_pending(db) == 0                      # no points yet
    work, _ = _point(db, "Work")
    _point(db, "Gym", pm=False, lat=51.4, lon=-0.2)
    pairs = commutes.pending_pairs(db, 10)
    assert len(pairs) == 3 and commutes.count_pending(db) == 3
    commutes.save_route(db, pairs[0], date(2026, 10, 20), None)                                          # "no journey" is remembered too
    assert commutes.count_pending(db) == 2
    commute_points.update(db, work, "Work", None, False)
    assert commutes.count_pending(db) == 1
    commutes.count_api_call(db)
    commutes.count_api_call(db, n=2)
    assert db.fetch_one("SELECT calls FROM api_usage WHERE provider = 'tfl'") == {"calls": 3}


def test_commute_filters_need_every_journey_of_each_chosen_point(db: Database) -> None:
    near, far = listings.insert_new(db, raw("a", address="A Road"))[1], listings.insert_new(db, raw("b", address="B Road"))[1]
    work, (w_am, w_pm) = _point(db, "Work")
    gym, (g_am,) = _point(db, "Gym", pm=False, lat=51.4, lon=-0.2)
    for pid, am, pm, g in ((near, 20, 25, 10), (far, 20, 50, 45)):
        _route(db, pid, w_am, am)
        _route(db, pid, w_pm, pm)
        _route(db, pid, g_am, g)

    def ids(*spec: str) -> set[int]:
        res = properties.search(db, q=None, min_rent=None, max_rent=None, min_beds=None, max_beds=None, borough=None,
                                commute=properties.parse_commute(db, list(spec)), furnished=None, sort="newest", order="asc",
                                limit=10, offset=0)
        return {r["id"] for r in res["rows"]}

    assert ids() == {near, far}
    assert ids(f"{work}:30") == {near}                      # the evening trip counts too
    assert ids(f"{work}:60", f"{gym}:20") == {near}         # several points, each with its own limit
    assert ids("all:30") == {near}                          # one limit for every active point
    assert ids(f"{work}:60", f"{gym}:60") == {near, far}
    with pytest.raises(Exception, match="commute filter"):
        properties.parse_commute(db, ["nonsense"])
    res = properties.search(db, q=None, min_rent=None, max_rent=None, min_beds=None, max_beds=None, borough=None, commute=[],
                            furnished=None, sort=f"commute:{gym}", order="asc", limit=10, offset=0)
    assert [r["id"] for r in res["rows"]] == [near, far] and len(res["rows"][0]["commutes"]) == 3
    _route(db, near, w_pm, None)                              # no route found for one journey
    assert ids(f"{work}:999") == {far}


def test_job_run_bookkeeping(db: Database) -> None:
    jobs.seed_settings(db, "j", 30, None, None)
    jobs.update_settings(db, "j", False, 45, "07:00", "22:00")
    jobs.seed_settings(db, "j", 30, None, None)                                          # never overwrites edits
    cfg = jobs.get_settings(db, "j")
    assert cfg["enabled"] is False and cfg["interval_minutes"] == 45
    run = jobs.start_run(db, "j", "manual")
    assert jobs.close_interrupted(db) == 1
    last = jobs.last_run(db, "j")
    assert last and last["status"] == "error" and "interrupted" in last["error"]
    run2 = jobs.start_run(db, "j", "schedule")
    jobs.finish_run(db, run2, "ok", 3, 1, {"x": 1}, None)
    assert jobs.last_ok(db, "j") is not None and run2 > run
    assert [r["id"] for r in jobs.recent_runs(db, 10)] == [run2, run]


def test_homes_in_switched_off_areas_are_hidden_and_come_back(db: Database) -> None:
    sw11 = areas.upsert(db, "SW11", "Battersea", True)
    areas.upsert(db, "KT1", "Kingston", True)
    listings.insert_new(db, raw("a", address="A"))
    listings.insert_new(db, raw("k", address="K", postcode="KT1 1AA"))
    nowhere = raw("n", address="N")
    nowhere.postcode = nowhere.outcode = None
    listings.insert_new(db, nowhere)                                           # no known outcode: never hidden
    assert filters.refresh(db) == {"hidden": 0, "restored": 0}
    areas.update(db, sw11, None, False)
    assert filters.refresh(db) == {"hidden": 1, "restored": 0}
    assert {r["address"] for r in db.fetch_all("SELECT address FROM v_properties")} == {"K", "N"}
    areas.update(db, sw11, None, True)
    assert filters.refresh(db) == {"hidden": 0, "restored": 1}
    assert db.fetch_one("SELECT count(*) AS n FROM v_properties") == {"n": 3}


def test_area_and_filter_rules_do_not_undo_each_other(db: Database) -> None:
    sw11 = areas.upsert(db, "SW11", "Battersea", True)
    listings.insert_new(db, raw("cheap", rent="1500", address="C"))
    listings.insert_new(db, raw("dear", rent="5000", address="D"))            # outside the rent filter
    filters.update(db, SearchFilters(min_bedrooms=None, max_bedrooms=None, max_rent=3500))
    areas.update(db, sw11, None, False)
    filters.refresh(db)                                                        # both hidden: one by area, one by area+rent
    areas.update(db, sw11, None, True)
    assert filters.refresh(db) == {"hidden": 0, "restored": 1}                # only the home inside the filters returns
    assert [r["address"] for r in db.fetch_all("SELECT address FROM v_properties")] == ["C"]
