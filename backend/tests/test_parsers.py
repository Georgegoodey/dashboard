"""Unit tests for the pure parsing and normalising code (no network, no database).

The Rightmove fixtures are trimmed real responses captured during the phase-0 spike; if Rightmove changes its page
format these tests fail loudly instead of the scraper quietly storing bad data.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.charts.infer import infer
from app.commute.tfl import best_journey, next_weekday, parse_journey
from app.pipeline.normalise import normalise_address, normalise_postcode, parse_date, pcm_from
from app.sources import rightmove as rm
from app.sources.base import RawListing, SearchFilters

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ── normalise ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_postcode_normalisation():
    assert normalise_postcode("sw117fd") == "SW11 7FD"
    assert normalise_postcode("SW11  7FD") == "SW11 7FD"
    assert normalise_postcode("London, W1G 0NB") == "W1G 0NB"
    assert normalise_postcode("SW11") is None          # an outcode alone is not a full postcode
    assert normalise_postcode(None) is None


def test_address_normalisation_makes_portals_comparable():
    a = normalise_address("Flat 3, 12 Embassy Boulevard, London SW11 7FD")
    b = normalise_address("Apartment 3 12 Embassy Blvd., London")
    assert a.startswith("flat 3 12 embassy")
    assert "sw11" not in a and "7fd" not in a            # the postcode is a separate field
    assert normalise_address("Rosenau Road,\nBattersea Park") == "rosenau rd battersea pk"
    assert b.startswith("flat 3 12")


def test_rent_period_conversion():
    assert pcm_from(4250, "monthly") == (Decimal("4250"), Decimal("980.77"))
    pcm, pw = pcm_from(500, "weekly")
    assert pcm == Decimal("2166.67") and pw == Decimal("500")
    assert pcm_from(None, "monthly") == (None, None)


def test_dates_accept_words_and_formats():
    assert parse_date("26/10/2026") == date(2026, 10, 26)
    assert parse_date("2026-10-26T00:00:00Z") == date(2026, 10, 26)
    assert parse_date("Ask agent") is None and parse_date("Now") is None


# ── rightmove ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_search_item_becomes_a_listing():
    fx = _load("rightmove_search_items.json")
    assert fx["resultCount"] and fx["offsets"][:3] == [0, 24, 48]     # 24 per page
    item = fx["properties"][0]
    listing = rm.listing_from_search_item(item)
    assert listing.source == "rightmove" and listing.source_listing_id == str(item["id"])
    assert listing.url == f"https://www.rightmove.co.uk/properties/{item['id']}"
    assert listing.rent_pcm and listing.lat and listing.lon
    assert "\n" not in listing.address                                # multi-line addresses are flattened
    assert listing.has_detail is False and listing.postcode is None   # detail comes later


def test_detail_page_fills_postcode_deposit_and_furnishing():
    for path in FIX.glob("rightmove_detail_*.json"):
        pd = _load(path.name)
        search_item = {"id": pd["id"], "displayAddress": pd["address"]["displayAddress"], "price": {"amount": 1000, "frequency": "monthly"},
                       "location": pd["location"]}
        listing = rm.listing_from_search_item(search_item)
        rm.apply_detail(listing, pd)
        assert listing.has_detail
        assert listing.postcode == normalise_postcode(f'{pd["address"]["outcode"]} {pd["address"]["incode"]}')
        assert listing.furnished and listing.let_type
        assert listing.description and "<" not in listing.description       # HTML stripped


def test_devalue_decoder_resolves_index_references():
    # root -> {"a": 1, "list": [2, 3]} where the referenced slots hold the values
    flat = [{"a": 1, "b": 4, "list": 5}, "x", 7, 8, {"deep": 1}, [2, 3]]
    out = rm.unflatten(flat)
    assert out["a"] == "x" and out["list"] == [7, 8] and out["b"]["deep"] == "x"


def test_page_model_extraction_from_html():
    flat = [{"propertyData": 1}, {"id": 2, "bedrooms": 3}, "123", 2]
    html = "<script>window.__PAGE_MODEL = " + json.dumps({"data": json.dumps(flat)}) + "</script>"
    pd = rm.parse_detail(html)
    assert pd == {"id": "123", "bedrooms": 2}


# ── tfl ─────────────────────────────────────────────────────────────────────────────────────────────────────────

JOURNEY = {
    "duration": 42, "startDateTime": "2026-10-20T08:05:00", "arrivalDateTime": "2026-10-20T08:47:00",
    "fare": {"totalCost": 310},
    "legs": [
        {"mode": {"name": "walking"}, "duration": 14, "instruction": {"summary": "Walk to Nine Elms Underground Station"}},
        {"mode": {"name": "tube"}, "duration": 2, "instruction": {"summary": "Northern line to Kennington"}},
        {"mode": {"name": "tube"}, "duration": 8, "instruction": {"summary": "Northern line to Bank"}},
        {"mode": {"name": "walking"}, "duration": 16, "instruction": {"summary": "Walk to EC2N 1HQ"}},
    ],
}


def test_tfl_journey_parsing():
    r = parse_journey(JOURNEY)
    assert r["duration_min"] == 42 and r["walk_min"] == 30
    assert r["transfers"] == 1                    # two tube legs = one change
    assert r["fare_pence"] == 310
    assert "Northern line to Bank" in r["summary"]


def test_best_journey_picks_the_shortest_and_handles_no_route():
    slower = {**JOURNEY, "duration": 60}
    best = best_journey({"journeys": [slower, JOURNEY]})
    assert best is not None and best["duration_min"] == 42
    assert best_journey({"journeys": []}) is None


def test_next_weekday_is_strictly_in_the_future():
    thursday = date(2026, 10, 15)
    assert next_weekday(1, thursday) == date(2026, 10, 20)       # Tuesday
    assert next_weekday(3, thursday) == date(2026, 10, 22)       # the next Thursday, not today
    assert next_weekday(5, thursday) == date(2026, 10, 17)       # Saturday


# ── chart inference on lettings-shaped results ──────────────────────────────────────────────────────────────────

def test_infer_group_by_borough_and_bedrooms():
    rows = [["Wandsworth", b, 10 + b, 3000.0 + 400 * b] for b in range(5)]
    spec = infer(["borough", "bedrooms", "homes", "avg_rent_pcm"], ["text", "int4", "int8", "numeric"], rows)["spec"]
    assert spec["x"] == "bedrooms" and spec["xKind"] == "category"          # bedrooms is a category, not a quantity
    assert any(s["field"] == "avg_rent_pcm" and s["format"] == "money" for s in spec["series"])
    assert any(s["kind"] == "bar" for s in spec["series"])


# ── search filters ──────────────────────────────────────────────────────────────────────────────────────────────

def _listing(beds, rent):
    return RawListing(source="rightmove", source_listing_id="1", url="u", address="a", bedrooms=beds,
                      rent_pcm=None if rent is None else Decimal(str(rent)))


def test_filters_accept_inside_and_reject_outside():
    f = SearchFilters(min_bedrooms=1, max_bedrooms=4, max_rent=3500)
    assert f.accepts(_listing(2, 3000))
    assert not f.accepts(_listing(0, 1500))          # studio is below the minimum
    assert not f.accepts(_listing(5, 3000))          # above the maximum
    assert not f.accepts(_listing(2, 4000))          # too expensive


def test_filters_keep_unknowns_and_tolerate_rounding():
    f = SearchFilters(min_bedrooms=1, max_bedrooms=4, max_rent=3500)
    assert f.accepts(_listing(None, None))           # nothing to judge, so keep it
    assert f.accepts(_listing(2, 3510))              # within 1% (weekly-to-monthly rounding)
    assert not f.accepts(_listing(2, 3600))


def test_no_limits_accepts_everything():
    f = SearchFilters(min_bedrooms=None, max_bedrooms=None, max_rent=None)
    assert f.accepts(_listing(0, 99999)) and f.accepts(_listing(9, 100))


def test_rightmove_search_params_carry_the_filters():
    p = rm.search_params("OUTCODE^2497", 24, SearchFilters(1, 4, 3500))
    assert p["minBedrooms"] == 1 and p["maxBedrooms"] == 4 and p["maxPrice"] == 3500
    assert p["index"] == 24 and p["channel"] == "RENT"
    bare = rm.search_params("OUTCODE^2497", 0, SearchFilters(None, None, None))
    assert not {"minBedrooms", "maxBedrooms", "maxPrice"} & set(bare)
    assert "minBedrooms" not in rm.search_params("OUTCODE^2497", 0)
