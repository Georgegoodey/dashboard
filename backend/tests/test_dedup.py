"""Cross-portal de-duplication: when two adverts are the same home, they should share one property.

Matching happens when a listing is first stored (`listings.insert_new`): exact on postcode, normalised address and bedrooms,
and never with a property that already has a listing from the same portal. The tests below pin down what works. Those marked
`xfail(strict=True)` are the gaps found by running the matcher against a real database of five portals (see the reasons): each
describes the behaviour wanted, and starts failing the build (as an unexpected pass) the day the gap is closed.
"""
from decimal import Decimal

import pytest

from app.db.database import Database
from app.pipeline.normalise import normalise_address
from app.repositories import listings
from app.sources.base import RawListing
from tests.test_repositories import raw


def advert(source: str, listing_id: str, **kw: object) -> RawListing:
    """An advert from `source` at 12 Embassy Boulevard, SW11 7FD, 2 beds, 2,000 pcm unless told otherwise."""
    base: dict[str, object] = {"address": "Flat 3, 12 Embassy Boulevard, London SW11 7FD", "rent": "2000"}
    return _with_source(raw(listing_id, **{**base, **kw}), source)  # type: ignore[arg-type]


def _with_source(item: RawListing, source: str) -> RawListing:
    item.source = source
    return item


def property_of(db: Database, source: str, listing_id: str) -> int:
    row = db.fetch_one("SELECT l.property_id FROM listings l JOIN sources s ON s.id = l.source_id "
                       "WHERE s.name = %s AND l.source_listing_id = %s", (source, listing_id))
    assert row is not None
    return int(row["property_id"])


def property_count(db: Database) -> int:
    row = db.fetch_one("SELECT count(*) AS n FROM properties")
    assert row is not None
    return int(row["n"])


# ── address normalisation (pure) ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b", [
    ("Amies Street, London SW11 2JW", "Amies Street, London, SW11 2JW"),
    ("12 Test Road,\nBattersea", "12 test rd battersea"),
    ("Flat 3, 12 Embassy Boulevard", "FLAT 3 12 EMBASSY BOULEVARD"),
    ("Apartment 4, Park Court", "Flat 4 Park Ct"),
])
def test_addresses_that_read_alike_normalise_alike(a: str, b: str) -> None:
    assert normalise_address(a) == normalise_address(b)


@pytest.mark.parametrize("a, b", [
    ("Flat 3, 12 Embassy Boulevard", "Flat 4, 12 Embassy Boulevard"),          # a different flat in the same block
    ("12 Test Road", "21 Test Road"),
    ("Park Court", "Park Close"),
])
def test_addresses_that_differ_stay_different(a: str, b: str) -> None:
    assert normalise_address(a) != normalise_address(b)


@pytest.mark.xfail(strict=True, reason="street-type abbreviations are a short fixed list: Boulevard/Blvd, Mansions/Mans, Heights/Hts are missing")
def test_more_street_type_abbreviations_are_understood() -> None:
    assert normalise_address("Flat 3, 12 Embassy Boulevard") == normalise_address("Flat 3, 12 Embassy Blvd")


# ── matching when the postcode is known at insert ───────────────────────────────────────────────────────────────

def test_the_same_home_on_two_portals_is_one_property(db: Database) -> None:
    listings.insert_new(db, advert("rightmove", "rm1"))
    listings.insert_new(db, advert("onthemarket", "otm1", address="Apartment 3, 12 Embassy Boulevard, London"))
    assert property_of(db, "rightmove", "rm1") == property_of(db, "onthemarket", "otm1") and property_count(db) == 1


def test_a_third_portal_joins_the_same_property(db: Database) -> None:
    for source, lid in (("rightmove", "rm1"), ("onthemarket", "otm1"), ("foxtons", "fx1")):
        listings.insert_new(db, advert(source, lid))
    assert property_count(db) == 1
    assert db.fetch_one("SELECT count(DISTINCT source_id) AS n FROM listings") == {"n": 3}


@pytest.mark.parametrize("change", [{"beds": 3}, {"postcode": "SW11 7FE"}, {"address": "Flat 4, 12 Embassy Boulevard, London SW11 7FD"}])
def test_homes_that_differ_in_bedrooms_postcode_or_flat_are_not_merged(db: Database, change: dict[str, object]) -> None:
    listings.insert_new(db, advert("rightmove", "rm1"))
    listings.insert_new(db, advert("onthemarket", "otm1", **change))
    assert property_count(db) == 2


def test_two_adverts_from_one_portal_are_never_merged(db: Database) -> None:
    listings.insert_new(db, advert("rightmove", "rm1"))
    listings.insert_new(db, advert("rightmove", "rm2"))              # another flat in a block with the same address
    assert property_count(db) == 2


def test_a_relisted_advert_keeps_its_property(db: Database) -> None:
    first, prop = listings.insert_new(db, advert("rightmove", "rm1"))
    again, same = listings.insert_new(db, advert("rightmove", "rm1", rent="2100"))
    assert (first, prop) == (again, same) and property_count(db) == 1


def test_matching_is_all_or_nothing_without_a_postcode(db: Database) -> None:
    item = advert("onthemarket", "otm1")
    item.postcode = None
    listings.insert_new(db, advert("rightmove", "rm1"))
    listings.insert_new(db, item)
    assert property_count(db) == 2                                    # without a postcode there is no key to match on


# ── the gaps ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="search results carry no postcode (only Rentola's do), so nothing is matched at insert; "
                                       "save_detail later fills the postcode in but never looks for a duplicate. "
                                       "On a real database this left 0 of 8,689 listings merged, while about 1,800 are one-to-one pairs")
def test_adverts_stored_without_a_postcode_are_merged_once_the_details_arrive(db: Database) -> None:
    rm, otm = advert("rightmove", "rm1"), advert("onthemarket", "otm1")
    rm.postcode = otm.postcode = None
    rm_id, _ = listings.insert_new(db, rm)
    otm_id, _ = listings.insert_new(db, otm)
    for listing_id, item in ((rm_id, rm), (otm_id, otm)):
        item.postcode = "SW11 7FD"
        listings.save_detail(db, listing_id, item)
    assert property_of(db, "rightmove", "rm1") == property_of(db, "onthemarket", "otm1")


@pytest.mark.xfail(strict=True, reason="the exact address key is too strict: 'Metropolitan Crescent, Clapham, London' and "
                                       "'Metropolitan Crescent, London SW4' are the same advert but normalise differently. "
                                       "Location (within about 30 m), bedrooms and rent find them where the text cannot")
def test_the_same_home_described_differently_is_still_one_property(db: Database) -> None:
    listings.insert_new(db, advert("rightmove", "rm1", address="Metropolitan Crescent, Clapham, London", lat=51.4631, lon=-0.1389))
    listings.insert_new(db, advert("onthemarket", "otm1", address="Metropolitan Crescent, London SW4", lat=51.4631, lon=-0.1389))
    assert property_count(db) == 1


@pytest.mark.xfail(strict=True, reason="an exact address match is joined without looking at the rent, so two 2-beds in one block "
                                       "(2,000 and 3,000 pcm) are paired in the order they arrive, which can attach the wrong one")
def test_two_flats_in_one_block_are_paired_by_rent_not_by_arrival_order(db: Database) -> None:
    listings.insert_new(db, advert("rightmove", "cheap", rent="2000"))
    listings.insert_new(db, advert("rightmove", "dear", rent="3000"))
    listings.insert_new(db, advert("onthemarket", "dear", rent="3000"))          # arrives first, and is the dearer flat
    assert property_of(db, "onthemarket", "dear") == property_of(db, "rightmove", "dear")
    assert property_of(db, "onthemarket", "dear") != property_of(db, "rightmove", "cheap")


def test_the_view_shows_a_merged_home_once_at_its_lowest_rent(db: Database) -> None:
    listings.insert_new(db, advert("rightmove", "rm1", rent="2000"))
    listings.insert_new(db, advert("onthemarket", "otm1", rent="1950"))
    rows = db.fetch_all("SELECT rent_pcm, sources FROM v_properties")
    assert len(rows) == 1 and rows[0]["rent_pcm"] == Decimal("1950.00") and rows[0]["sources"] == "onthemarket, rightmove"
