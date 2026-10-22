"""Foxtons and Rentola: parsing against saved pages, and the adapters' paging and politeness against a fake site.

The fixtures are trimmed copies of real pages; if a site changes its page format these tests fail loudly instead of the
scraper quietly storing bad data.
"""
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.sources import foxtons as fx
from app.sources import rentola as rl
from app.sources.base import Blocked, Incomplete, NotFound, RawListing, Throttle

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _fast() -> Throttle:
    return Throttle(min_delay=0, jitter=0)


# ── Foxtons ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_foxtons_search_page_becomes_listings_and_skips_sales() -> None:
    items, pages, searched = fx.search_page_info(_read("foxtons_search.html"))
    assert (len(items), pages, searched) == (5, 4, "SW11")
    listings = [fx.listing_from_search_item(i) for i in items]
    assert [x.source_listing_id if x else None for x in listings] == ["chpk0447643", "nwhm4558384", "chpk3580377", "chpk4664083", None]
    first = listings[0]
    assert first is not None and first.source == "foxtons"
    assert first.url == "https://www.foxtons.co.uk/properties-to-rent/SW11/chpk0447643"
    assert first.address == "Cambridge Road, Battersea Park, SW11" and first.outcode == "SW11"
    assert (first.bedrooms, first.bathrooms, first.property_type) == (5, 3, "House")
    assert first.rent_pcm == Decimal("8000") and first.rent_pw == Decimal("1846.15")           # priceFrom is the weekly rent
    assert first.lat == pytest.approx(51.473, abs=1e-3) and first.agent_name == "Foxtons, Battersea"


def test_foxtons_advert_page_fills_in_the_details() -> None:
    items, _, _ = fx.search_page_info(_read("foxtons_search.html"))
    listing = fx.listing_from_search_item(items[0])
    pd = fx.parse_detail(_read("foxtons_detail.html"))
    assert listing is not None and pd is not None
    fx.apply_detail(listing, pd)
    assert listing.postcode == "SW11 8BG" and listing.outcode == "SW11" and listing.property_type == "Flat" and listing.has_detail
    assert "Communal garden" in listing.key_features and "Landlord accepts zero deposit" in listing.key_features
    assert fx.parse_detail("<html>no data</html>") is None


def _fox_site(requests: list[httpx.Request], pages: int = 3) -> httpx.MockTransport:
    page = _read("foxtons_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        n = int(parse_qs(request.url.query.decode()).get("page", ["1"])[0])
        body = page.replace('"totalPages": 4', f'"totalPages": {pages}')
        for ref in ("chpk0447643", "nwhm4558384", "chpk3580377", "chpk4664083"):
            body = body.replace(ref, f"{ref}{n}")
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


async def test_foxtons_walks_the_pages_with_only_the_page_parameter() -> None:
    requests: list[httpx.Request] = []
    src = fx.Foxtons(throttle=_fast())
    async with httpx.AsyncClient(transport=_fox_site(requests)) as client:
        found = [item async for item in src.search(client, "sw11")]
        assert await src.resolve_area(client, "SW11") == "sw11" and await src.resolve_area(client, "nonsense") is None
    assert len(found) == 12 and [r.url.path for r in requests] == ["/properties-to-rent/sw11"] * 3
    assert [parse_qs(r.url.query.decode()).get("page") for r in requests] == [None, ["2"], ["3"]]
    forbidden = ("radius", "order_by", "prop_type", "expand", "sold")
    assert all(not any(f in r.url.query.decode() for f in forbidden) for r in requests)


async def test_foxtons_regional_fallback_for_an_unknown_outcode_is_not_taken_for_results() -> None:
    page = _read("foxtons_search.html").replace('"searchedText": "SW11"', '"searchedText": "South East England"')
    src = fx.Foxtons(throttle=_fast())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page))) as client:
        with pytest.raises(NotFound):
            [i async for i in src.search(client, "sw11")]
    other = _read("foxtons_search.html").replace('"postcodeShort": "SW11"', '"postcodeShort": "SW8"')        # a neighbour's listings
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=other))) as client:
        assert [i async for i in src.search(client, "sw11")] == []


async def test_foxtons_removed_advert_redirects_to_a_search_page() -> None:
    src = fx.Foxtons(throttle=_fast())
    listing = RawListing(source="foxtons", source_listing_id="x", url="https://www.foxtons.co.uk/properties-to-rent/SW11/x", address="x")
    search_page = _read("foxtons_search.html")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=search_page))) as client:
        with pytest.raises(NotFound):
            await src.fetch_detail(client, listing)


async def test_foxtons_challenge_and_missing_pages() -> None:
    src = fx.Foxtons(throttle=_fast())
    listing = RawListing(source="foxtons", source_listing_id="x", url="https://www.foxtons.co.uk/properties-to-rent/SW11/x", address="x")
    for status, error in ((403, Blocked), (404, NotFound)):
        site = httpx.MockTransport(lambda r, s=status: httpx.Response(s, text="no"))
        async with httpx.AsyncClient(transport=site) as client:
            with pytest.raises(error):
                await src.fetch_detail(client, listing)
    plain = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>layout changed</html>"))
    async with httpx.AsyncClient(transport=plain) as client:
        with pytest.raises(Blocked):
            [i async for i in src.search(client, "sw11")]


# ── Rentola ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rentola_keeps_its_own_listings_and_skips_copies_and_rooms() -> None:
    items = rl.search_page_info(_read("rentola_search.html"))
    assert [i.source_listing_id for i in items] == ["p5e5000", "pd866fb"]                   # not the copies, the share or the room
    first = items[0]
    assert first.source == "rentola" and first.url == "https://rentola.co.uk/listings/2-bedroom-flat-in-london-p5e5000"
    assert first.address == "Cumberland Terrace, London, NW1 4HP" and first.postcode == "NW1 4HP" and first.outcode == "NW1"
    assert (first.bedrooms, first.property_type, first.rent_pcm) == (2, "Flat", Decimal("1150"))
    assert first.rent_pw == Decimal("265.38") and first.lat == pytest.approx(51.531, abs=1e-3)
    assert rl.is_copy("Bovingdon Avenue, Wembley HA9, 3 bed bungalow to rent, £2,700 pcm | PrimeLocation")
    assert rl.is_copy("Strathblaine Road, London SW11 2 bed flat to rent - £2,750 pcm (£635 pw)")
    assert not rl.is_copy("2 bedroom flat in London")


def test_rentola_advert_page_fills_in_the_details() -> None:
    listing = rl.search_page_info(_read("rentola_search.html"))[0]
    ld = rl.parse_detail(_read("rentola_detail.html"))
    assert ld is not None
    rl.apply_detail(listing, ld)
    assert listing.description and listing.description.startswith("24 hour porter\noff street parking") and listing.has_detail
    assert listing.bathrooms == 1 and listing.key_features == ["55 sq m floor area"] and listing.first_listed is not None
    assert rl.parse_detail("<html>no data</html>") is None


async def test_rentola_only_covers_london_postcodes() -> None:
    src = rl.Rentola(throttle=_fast())
    async with httpx.AsyncClient() as client:
        assert [await src.resolve_area(client, c) for c in ("SW11", "kt1", "TW9", "M1", "B1", "nonsense")] == [
            "sw11", "kt1", "tw9", None, None, None]


def _rentola_site(requests: list[httpx.Request], pages_per_view: int = 2) -> httpx.MockTransport:
    page = _read("rentola_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        n = int(parse_qs(request.url.query.decode()).get("page", ["1"])[0])
        if n > pages_per_view:
            return httpx.Response(404, text="Page not found")
        view = request.url.path.split("/property-to-rent/")[1]
        return httpx.Response(200, text=page.replace("p5e5000", f"p5e5000{n}").replace("pd866fb", f"pd866fb{view[:2]}"))

    return httpx.MockTransport(handler)


async def test_rentola_walks_every_view_once_and_filters_by_outcode() -> None:
    requests: list[httpx.Request] = []
    src = rl.Rentola(throttle=_fast(), views=("flat/1-bedroom", "studio-flat"))
    async with httpx.AsyncClient(transport=_rentola_site(requests)) as client:
        found: list[RawListing] = []
        with pytest.raises(Incomplete):                                                    # a sample, never the whole
            async for item in src.search(client, "nw1"):
                found.append(item)
        assert {i.outcode for i in found} == {"NW1"} and len(found) == len({i.source_listing_id for i in found}) == 4
        n = len(requests)
        with pytest.raises(Incomplete):
            [i async for i in src.search(client, "sw11")]                                  # another outcode: served from the cache
    assert len(requests) == n == 6                                                         # 2 views x (2 pages + the 404 that ends it)
    paths = {r.url.path for r in requests}
    assert paths == {"/property-to-rent/flat/1-bedroom/london", "/property-to-rent/studio-flat/london"}
    assert all(parse_qs(r.url.query.decode()).get("page") != ["1"] for r in requests)      # page 1 is the plain URL


async def test_rentola_challenge_and_layout_changes() -> None:
    src = rl.Rentola(throttle=_fast(), views=("studio-flat",))
    for site, error in ((httpx.MockTransport(lambda r: httpx.Response(429, text="slow")), Blocked),
                        (httpx.MockTransport(lambda r: httpx.Response(200, text="<html>layout changed</html>")), Blocked),
                        (httpx.MockTransport(lambda r: httpx.Response(404, text="gone")), NotFound)):
        async with httpx.AsyncClient(transport=site) as client:
            with pytest.raises(error):
                [i async for i in src.search(client, "sw11")]
    listing = RawListing(source="rentola", source_listing_id="p1", url="https://rentola.co.uk/listings/x-p1", address="x")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))) as client:
        with pytest.raises(Blocked):
            await src.fetch_detail(client, listing)


def test_the_new_portals_pace_themselves() -> None:
    assert fx.Foxtons().throttle.min_delay >= 3 and rl.Rentola().throttle.min_delay >= 4
