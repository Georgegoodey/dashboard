"""OnTheMarket and OpenRent: parsing against saved pages, and the adapters' paging and politeness against a fake site.

The fixtures are trimmed copies of real pages; if a portal changes its page format these tests fail loudly instead of the
scraper quietly storing bad data.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.pipeline.normalise import html_to_text, outcode_from_text
from app.sources import onthemarket as otm
from app.sources import openrent as orr
from app.sources.base import Blocked, NotFound, RawListing, Throttle

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _fast() -> Throttle:
    return Throttle(min_delay=0, jitter=0)


# ── shared helpers ──────────────────────────────────────────────────────────────────────────────────────────────

def test_outcode_is_read_from_the_end_of_an_address() -> None:
    assert outcode_from_text("Nantes Close, London SW18") == "SW18"
    assert outcode_from_text("Battersea Rise, sw11") == "SW11"
    assert outcode_from_text("2 Bedroom Apartment To Let, Canary Wharf") is None


def test_html_becomes_text_with_line_breaks() -> None:
    text = html_to_text("<p>One &amp; two</p><ul><li>Garden<br></li><li>Parking</li></ul>Last<br>line")
    assert text == "One & two\n\nGarden\nParking\nLast\nline"
    assert html_to_text(None) is None and html_to_text("  ") is None


# ── OnTheMarket ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_onthemarket_search_page_becomes_listings() -> None:
    items, pages, shown = otm.search_page_info(otm.extract_next_data(_read("onthemarket_search.html")) or {})
    assert len(items) == 4 and pages == 28 and shown == "sw11"
    first = otm.listing_from_search_item(items[0], "SW11")
    assert (first.source, first.source_listing_id) == ("onthemarket", "20480488")
    assert first.url == "https://www.onthemarket.com/details/20480488/"
    assert first.rent_pcm == Decimal("1845") and first.rent_pw == Decimal("425.77")
    assert first.bedrooms == 1 and first.outcode == "SW18" and first.property_type == "Flat"
    assert first.lat == pytest.approx(51.4617, abs=1e-3) and first.agent_name == "New Brix - Surrey"
    assert first.headline == "Offered unfurnished."                       # viewing times are not a headline
    no_outcode = otm.listing_from_search_item(items[1], "SW11")
    assert no_outcode.outcode == "SW11"                                    # falls back to the area searched


def test_onthemarket_prices_in_other_periods_and_on_request() -> None:
    assert otm.price_from("£1,845 pcm (£426 pw)") == (Decimal("1845"), Decimal("425.77"))
    pcm, pw = otm.price_from("£500 pw")
    assert pcm == Decimal("2166.67") and pw == Decimal("500")
    assert otm.price_from("Price on application") == (None, None) and otm.price_from(None) == (None, None)


def test_onthemarket_advert_page_fills_in_the_details() -> None:
    items, _, _ = otm.search_page_info(otm.extract_next_data(_read("onthemarket_search.html")) or {})
    listing = otm.listing_from_search_item(items[0], "SW11")
    pd = otm.parse_detail(_read("onthemarket_detail.html"))
    assert pd is not None
    otm.apply_detail(listing, pd)
    assert listing.postcode == "SW18 1JL" and listing.outcode == "SW18"
    assert listing.deposit == Decimal("2000") and listing.furnished == "Unfurnished" and listing.let_type == "Long term"
    assert listing.available_from == date(2026, 12, 8) and listing.has_detail
    assert listing.description and listing.description.startswith("Newbrix is pleased") and "<br" not in listing.description
    assert otm.parse_detail("<html>no data</html>") is None


def _otm_site(requests: list[httpx.Request], pages: int = 3, known: str = "sw11") -> httpx.MockTransport:
    page = _read("onthemarket_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path != f"/to-rent/property/{known}/":
            return httpx.Response(404, text="not found")
        n = int(parse_qs(request.url.query.decode()).get("page", ["1"])[0])
        # every page is the saved page with its ids shifted, so paging is visible and last-link says `pages`
        body = page.replace('"last-link": {"url": "/to-rent/property/sw11/?page=28", "page": 28}', f'"last-link": {{"page": {pages}}}')
        for old in ("20480488", "20576839", "20499332", "19798602"):
            body = body.replace(old, f"{old}{n}")
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


async def test_onthemarket_walks_the_pages_without_the_parameters_robots_txt_forbids() -> None:
    requests: list[httpx.Request] = []
    src = otm.OnTheMarket(throttle=_fast())
    async with httpx.AsyncClient(transport=_otm_site(requests)) as client:
        found = [item async for item in src.search(client, "sw11")]
    assert len(found) == 12 and len({i.source_listing_id for i in found}) == 12      # 3 pages of 4
    assert [parse_qs(r.url.query.decode()).get("page") for r in requests] == [None, ["2"], ["3"]]
    forbidden = ("min-price", "max-price", "min-bedrooms", "max-bedrooms", "sort-field", "radius", "prop-types", "direction", "view")
    assert all(not any(f in r.url.query.decode() for f in forbidden) for r in requests)


async def test_onthemarket_unknown_area_and_challenge_pages() -> None:
    src = otm.OnTheMarket(throttle=_fast())
    async with httpx.AsyncClient(transport=_otm_site([], known="sw99")) as client:
        with pytest.raises(NotFound):
            [i async for i in src.search(client, "sw11")]
        assert await src.resolve_area(client, "SW11") == "sw11" and await src.resolve_area(client, "nonsense") is None
    blocked = httpx.MockTransport(lambda r: httpx.Response(403, text="Just a moment..."))
    async with httpx.AsyncClient(transport=blocked) as client:
        with pytest.raises(Blocked):
            [i async for i in src.search(client, "sw11")]
    empty = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>layout changed</html>"))
    listing = RawListing(source="onthemarket", source_listing_id="1", url="https://www.onthemarket.com/details/1/", address="x")
    async with httpx.AsyncClient(transport=empty) as client:
        with pytest.raises(Blocked):
            await src.fetch_detail(client, listing)
    gone = httpx.MockTransport(lambda r: httpx.Response(404, text="gone"))
    async with httpx.AsyncClient(transport=gone) as client:
        with pytest.raises(NotFound):
            await src.fetch_detail(client, listing)


# ── OpenRent ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_openrent_search_page_becomes_listings_and_skips_rooms() -> None:
    items, total, per_page = orr.search_page_info(_read("openrent_search.html"))
    assert total == 163 and per_page == 20
    assert items and all(i.source == "openrent" and i.outcode == "SW11" for i in items)
    assert not any("room" in (i.property_type or "").lower() for i in items)                  # shared rooms are left out
    first = items[0]
    assert first.source_listing_id == "3076759" and first.address == "Battersea, SW11"
    assert first.url == "https://www.openrent.co.uk/property-to-rent/london/2-bed-flat-battersea-sw11/3076759"
    assert (first.bedrooms, first.bathrooms, first.property_type) == (2, 1, "Flat")
    assert first.rent_pcm == Decimal("2600") and first.rent_pw == Decimal("600") and first.furnished == "Furnished"
    assert (first.lat, first.lon) == (51.46844, -0.1730653)                                   # from the parallel arrays


def test_openrent_advert_page_fills_in_the_details() -> None:
    items, _, _ = orr.search_page_info(_read("openrent_search.html"))
    listing = items[0]
    orr.apply_detail(listing, _read("openrent_detail.html"))
    assert listing.deposit == Decimal("3000") and listing.rent_pcm == Decimal("2600")
    assert listing.furnished == "Furnished" and listing.min_term_months == 1 and listing.available_from is None   # "Today"
    assert (listing.lat, listing.lon) == (51.46844, -0.1730653) and (listing.bedrooms, listing.bathrooms) == (2, 1)
    assert "Parking" in listing.key_features and "Student Friendly" in listing.key_features
    assert "Garden" not in listing.key_features and "Bills Included" not in listing.key_features      # crossed rows
    assert listing.description and listing.description.startswith("This is a superb apartment")
    assert "Read more" not in listing.description and listing.has_detail


def test_openrent_let_adverts_are_recognised() -> None:
    assert orr.is_let("<div>Let Agreed - This property is no longer available for rent</div>")
    assert not orr.is_let(_read("openrent_detail.html"))


def _or_site(requests: list[httpx.Request]) -> httpx.MockTransport:
    page = _read("openrent_search.html")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        skip = int(parse_qs(request.url.query.decode()).get("skip", ["0"])[0])
        body = page.replace("3076759", f"30767{skip}").replace("3060978", f"30609{skip}")
        # a neighbouring outcode picked up by the search radius, on every page
        body = body.replace("York Road, SW11", "York Road, SW18").replace("york-road-sw11", "york-road-sw18") if skip == 0 else body
        return httpx.Response(200, text=body.replace("var NUMBEROFPROPERTIES = 163", "var NUMBEROFPROPERTIES = 45"))

    return httpx.MockTransport(handler)


async def test_openrent_pages_with_skip_and_keeps_only_the_requested_outcode() -> None:
    requests: list[httpx.Request] = []
    src = orr.OpenRent(throttle=_fast())
    async with httpx.AsyncClient(transport=_or_site(requests)) as client:
        found = [item async for item in src.search(client, "sw11")]
    queries = [parse_qs(urlparse(str(r.url)).query) for r in requests]
    assert [q.get("skip") for q in queries] == [None, ["20"], ["40"]] and all(q["term"] == ["SW11"] for q in queries)
    assert all(i.outcode == "SW11" for i in found)
    assert not any(i.address.endswith("SW18") for i in found)               # the neighbour from page 1 was dropped
    assert len({i.source_listing_id for i in found}) == len(found)


async def test_openrent_stops_paging_once_the_results_have_left_the_outcode() -> None:
    requests: list[httpx.Request] = []
    page = _read("openrent_search.html").replace("SW11", "SW18").replace("sw11", "sw18")      # nothing here is in SW11

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=page.replace("var NUMBEROFPROPERTIES = 163", "var NUMBEROFPROPERTIES = 400"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = [item async for item in orr.OpenRent(throttle=_fast()).search(client, "sw11")]
    assert found == [] and len(requests) == orr.EMPTY_PAGES_TO_STOP                              # 20 pages were on offer


async def test_a_429_stops_the_run_and_passes_on_the_wait() -> None:
    limited = httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "120"}, text="slow down"))
    async with httpx.AsyncClient(transport=limited) as client:
        with pytest.raises(Blocked, match="HTTP 429, asks to wait 120s"):
            [i async for i in orr.OpenRent(throttle=_fast()).search(client, "sw11")]


def test_the_portals_default_to_a_slow_pace() -> None:
    assert orr.OpenRent().throttle.min_delay >= 5 and otm.OnTheMarket().throttle.min_delay >= 3


async def test_openrent_let_and_challenge_pages() -> None:
    src = orr.OpenRent(throttle=_fast())
    listing = RawListing(source="openrent", source_listing_id="1", url="https://www.openrent.co.uk/property-to-rent/x/1", address="x")
    let = httpx.MockTransport(lambda r: httpx.Response(200, text="Let Agreed - This property is no longer available for rent"))
    async with httpx.AsyncClient(transport=let) as client:
        with pytest.raises(NotFound):
            await src.fetch_detail(client, listing)
    odd = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>layout changed</html>"))
    async with httpx.AsyncClient(transport=odd) as client:
        with pytest.raises(Blocked):
            await src.fetch_detail(client, listing)
        with pytest.raises(Blocked):
            [i async for i in src.search(client, "sw11")]
    ok = httpx.MockTransport(lambda r: httpx.Response(200, text=_read("openrent_detail.html")))
    async with httpx.AsyncClient(transport=ok) as client:
        done = await src.fetch_detail(client, listing)
    assert done.has_detail and done.deposit == Decimal("3000")
