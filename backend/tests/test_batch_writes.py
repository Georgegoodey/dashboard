"""Storing adverts in batches (insert_many, touch_known) must give exactly what storing them one at a time gave."""
from decimal import Decimal

import pytest

from app.db.database import Database
from app.repositories import listings
from app.sources.base import RawListing
from tests.test_repositories import raw

pytestmark = pytest.mark.integration


def advert(source: str, listing_id: str, **kw: object) -> RawListing:
    item = raw(listing_id, **kw)  # type: ignore[arg-type]
    item.source = source
    return item


def count(db: Database, table: str) -> int:
    row = db.fetch_one(f"SELECT count(*) AS n FROM {table}")
    assert row is not None
    return int(row["n"])


def test_a_batch_stores_every_advert_with_a_property_and_a_first_price(db: Database) -> None:
    items = [raw(str(i), rent=str(1000 + i), address=f"{i} Test Road") for i in range(5)]
    stored = listings.insert_many(db, items)
    assert len(stored) == 5 and len({lid for lid, _ in stored}) == 5 and len({pid for _, pid in stored}) == 5
    assert count(db, "listings") == count(db, "properties") == count(db, "listing_price_history") == 5
    row = db.fetch_one("SELECT l.rent_pcm FROM listings l WHERE l.source_listing_id = '3'")
    assert row == {"rent_pcm": Decimal("1003.00")}
    assert listings.insert_many(db, []) == []


def test_results_come_back_in_the_order_given(db: Database) -> None:
    first, second = listings.insert_many(db, [raw("b", address="B Road"), raw("a", address="A Road")])
    row = db.fetch_one("SELECT source_listing_id FROM listings WHERE id = %s", (first[0],))
    assert row == {"source_listing_id": "b"} and second[0] != first[0]


def test_two_adverts_from_one_portal_in_one_batch_never_share_a_property(db: Database) -> None:
    other = advert("onthemarket", "o1")
    listings.insert_new(db, other)                                          # one property already, from another portal
    stored = listings.insert_many(db, [advert("rightmove", "r1"), advert("rightmove", "r2")])     # same address, postcode, beds
    assert stored[0][1] != stored[1][1]                                       # only one of them may join the existing property
    assert count(db, "properties") == 2


def test_a_batch_matches_an_existing_property_from_another_portal(db: Database) -> None:
    _, existing = listings.insert_new(db, advert("rightmove", "r1"))
    stored = listings.insert_many(db, [advert("onthemarket", "o1"), advert("onthemarket", "o2", address="Elsewhere, SW11")])
    assert stored[0][1] == existing and stored[1][1] != existing


def test_adverts_already_stored_or_repeated_in_the_batch_are_not_stored_twice(db: Database) -> None:
    (lid, pid), = listings.insert_many(db, [raw("1")])
    db.execute("UPDATE listings SET status = 'withdrawn', missed_scrapes = 2 WHERE id = %s", (lid,))
    again = listings.insert_many(db, [raw("1"), raw("2", address="2 Road"), raw("2", address="2 Road")])
    assert again[0] == (lid, pid) and again[1] == again[2]
    assert count(db, "listings") == 2 and count(db, "properties") == 2 and count(db, "listing_price_history") == 2
    assert db.fetch_one("SELECT status, missed_scrapes FROM listings WHERE id = %s", (lid,)) == {"status": "active", "missed_scrapes": 0}


def test_a_batch_can_mix_portals(db: Database) -> None:
    stored = listings.insert_many(db, [advert("rightmove", "r1"), advert("onthemarket", "o1")])
    assert stored[0][1] == stored[1][1] and count(db, "listings") == 2          # the same home on two portals


def test_touch_known_updates_many_adverts_at_once(db: Database) -> None:
    ids = listings.insert_many(db, [raw(str(i), rent="2000", address=f"{i} Test Road") for i in range(4)])
    db.execute("UPDATE listings SET status = 'withdrawn', missed_scrapes = 3 WHERE id = %s", (ids[0][0],))
    db.execute("UPDATE listings SET last_seen = now() - interval '3 days'")
    batch = [raw("0", rent="2000", address="0 Test Road"), raw("1", rent="1900", address="1 Test Road"),
             raw("2", rent="2100", address="2 Test Road"), raw("9", rent="500", address="9 Test Road")]       # 9 is not stored
    result = listings.touch_known(db, "rightmove", batch)
    assert result == {"touched": 3, "repriced": 2, "revived": 1}
    rows = {r["source_listing_id"]: r for r in db.fetch_all("SELECT source_listing_id, rent_pcm, status, missed_scrapes, "
                                                            "last_seen > now() - interval '1 minute' AS fresh FROM listings")}
    assert rows["0"]["status"] == "active" and rows["0"]["missed_scrapes"] == 0 and rows["0"]["fresh"]
    assert rows["1"]["rent_pcm"] == Decimal("1900.00") and rows["2"]["rent_pcm"] == Decimal("2100.00")
    assert rows["3"]["fresh"] is False and rows["3"]["rent_pcm"] == Decimal("2000.00")                     # not in the batch: untouched
    history = db.fetch_all("SELECT l.source_listing_id, h.rent_pcm FROM listing_price_history h JOIN listings l ON l.id = h.listing_id "
                           "WHERE l.source_listing_id IN ('1', '2') ORDER BY h.id")
    assert [(h["source_listing_id"], h["rent_pcm"]) for h in history] == [
        ("1", Decimal("2000.00")), ("2", Decimal("2000.00")), ("1", Decimal("1900.00")), ("2", Decimal("2100.00"))]
    assert listings.touch_known(db, "rightmove", []) == {"touched": 0, "repriced": 0, "revived": 0}


def test_adverts_can_be_stored_and_refreshed_as_hidden(db: Database) -> None:
    listings.insert_many(db, [raw("a", address="A Road")], status="filtered")
    assert db.fetch_one("SELECT status FROM listings") == {"status": "filtered"}
    result = listings.touch_known(db, "rightmove", [raw("a", rent="2100", address="A Road")], status="filtered")
    assert result == {"touched": 1, "repriced": 1, "revived": 0}
    assert db.fetch_one("SELECT status, rent_pcm FROM listings") == {"status": "filtered", "rent_pcm": Decimal("2100.00")}
    listings.touch_known(db, "rightmove", [raw("a", rent="2100", address="A Road")])               # the filters loosened
    assert db.fetch_one("SELECT status FROM listings") == {"status": "active"}
    listings.insert_many(db, [raw("a", address="A Road")], status="filtered")                          # and tightened again
    assert db.fetch_one("SELECT status FROM listings") == {"status": "filtered"}


def test_the_filter_sweep_hides_garages_and_parking(db: Database) -> None:
    from app.repositories import areas
    from app.sources.base import SearchFilters

    areas.upsert(db, "SW11", "Battersea", True)
    garage = raw("g", address="Garage, A Road")
    garage.property_type = "Garage"
    listings.insert_many(db, [garage, raw("flat", address="B Road")])
    result = listings.apply_filters(db, SearchFilters(min_bedrooms=None, max_bedrooms=None, max_rent=None))
    assert result == {"hidden": 1, "restored": 0}
    assert db.fetch_one("SELECT status FROM listings l JOIN properties p ON p.id = l.property_id WHERE p.property_type = 'Garage'") == {
        "status": "filtered"}


def test_touch_known_only_touches_the_properties_of_the_adverts_it_saw(db: Database) -> None:
    """The old statement matched on the portal's id alone, so another portal's advert with the same id was touched too."""
    (_, mine), = listings.insert_many(db, [advert("rightmove", "same-id", address="A Road")])
    (_, theirs), = listings.insert_many(db, [advert("onthemarket", "same-id", address="B Road", beds=3)])
    db.execute("UPDATE properties SET last_seen = now() - interval '3 days'")
    listings.touch_known(db, "rightmove", [advert("rightmove", "same-id", address="A Road")])
    fresh = {r["id"]: r["fresh"] for r in db.fetch_all("SELECT id, last_seen > now() - interval '1 minute' AS fresh FROM properties")}
    assert fresh[mine] is True and fresh[theirs] is False
