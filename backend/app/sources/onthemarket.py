"""OnTheMarket adapter (plain HTTP, no browser).

Findings from looking at the live site and its robots.txt:
- Search and advert pages are Next.js pages: the whole result set is embedded as JSON in a `__NEXT_DATA__` script tag
  (`props.pageProps.initialReduxState`). Searches show 30 results a page, `?page=N`, up to about 28 pages for an outcode.
- robots.txt disallows the price, bedroom, sort, radius and property-type query parameters (and the `*-bed-` URLs), so this
  adapter requests only the plain area page, `/to-rent/property/<outcode>/`, and applies the search filters itself.
- Advert pages (`/details/<id>/`) hold the exact postcode (in the page's data layer), the lettings details (deposit,
  furnishing, availability), the coordinates and the full description.
"""
import json
import re
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from app.pipeline.normalise import OUTCODE_RE, html_to_text, normalise_postcode, outcode_from_text, parse_date, pcm_from
from app.sources.base import Blocked, NotFound, RawListing, SearchFilters, Throttle
from app.sources.http import polite_get
from app.sources.rightmove import extract_next_data

BASE = "https://www.onthemarket.com"
MAX_PAGES = 40
_PRICE_RE = re.compile(r"£\s*([\d,]+(?:\.\d+)?)\s*(pcm|pw)", re.I)


# ── parsing (pure functions, unit-tested against saved fixtures) ─────────────────────────────────────────────────

def _state(data: dict) -> dict:
    state = ((data.get("props") or {}).get("pageProps") or {}).get("initialReduxState")
    return state if isinstance(state, dict) else {}


def search_page_info(data: dict) -> tuple[list[dict], int, str | None]:
    """(result items, number of pages, location id the page was actually for) from a parsed search page."""
    results = _state(data).get("results") or {}
    controls = results.get("paginationControls") or {}
    last = (controls.get("last-link") or {}).get("page")
    pages = last or max([p.get("page", 1) for p in controls.get("page-links") or []] or [1])
    location = (results.get("currentQuery") or {}).get("location-id")
    return list(results.get("list") or []), int(pages), str(location).lower() if location else None


def price_from(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """(rent_pcm, rent_pw) from '£1,845 pcm (£426 pw)'. Prices on request or without a period give (None, None)."""
    m = _PRICE_RE.search(text or "")
    if not m:
        return None, None
    amount = Decimal(m.group(1).replace(",", ""))
    return pcm_from(int(amount) if amount == amount.to_integral() else float(amount), m.group(2).lower())


def listing_from_search_item(p: dict, default_outcode: str | None = None) -> RawListing:
    pid = str(p["id"])
    pcm, pw = price_from(p.get("price"))
    loc = p.get("location") or {}
    features = [str(f).strip() for f in p.get("features") or [] if str(f).strip()]
    return RawListing(
        source="onthemarket",
        source_listing_id=pid,
        url=f"{BASE}{p.get('details-url') or f'/details/{pid}/'}",
        address=re.sub(r"\s*[\r\n]+\s*", ", ", (p.get("address") or "").strip()),
        outcode=outcode_from_text(p.get("address")) or default_outcode,
        lat=loc.get("lat"),
        lon=loc.get("lon"),
        bedrooms=p.get("bedrooms"),
        bathrooms=p.get("bathrooms"),
        property_type=p.get("humanised-property-type"),
        rent_pcm=pcm,
        rent_pw=pw,
        agent_name=(p.get("agent") or {}).get("name"),
        headline=next((f for f in features if not f.lower().startswith("viewings")), None),
        key_features=features,
        raw={"price": p.get("price"), "label": p.get("main-label"), "added": p.get("days-since-added-reduced")},
    )


def parse_detail(html: str) -> dict | None:
    """The `property` object from an advert page, or None if the page has no usable payload."""
    data = extract_next_data(html)
    prop = _state(data).get("property") if data else None
    return prop if isinstance(prop, dict) and prop.get("id") else None


def _postcode_from(pd: dict) -> str | None:
    layer = (pd.get("headerData") or {}).get("dataLayer")
    try:
        found = json.loads(layer).get("postcode") if isinstance(layer, str) else None
    except ValueError:
        found = None
    return normalise_postcode(found)


def apply_detail(listing: RawListing, pd: dict) -> RawListing:
    """Fill a search-level listing with what only the advert page knows."""
    listing.postcode = _postcode_from(pd) or listing.postcode
    if listing.postcode:
        listing.outcode = listing.postcode.split()[0]
    if pd.get("displayAddress"):
        listing.address = re.sub(r"\s*[\r\n]+\s*", ", ", pd["displayAddress"].strip())
    loc = pd.get("location") or {}
    if loc.get("lat") is not None:
        listing.lat, listing.lon = loc["lat"], loc["lon"]

    for item in (pd.get("lettingDetails") or {}).get("items") or []:
        text = str(item).strip()
        low = text.lower()
        if low.startswith("availability date"):
            listing.available_from = parse_date(text.split(":", 1)[-1].strip()) or listing.available_from
        elif low.startswith("deposit"):
            m = re.search(r"([\d,]+(?:\.\d+)?)", text)
            listing.deposit = Decimal(m.group(1).replace(",", "")) if m and Decimal(m.group(1).replace(",", "")) else None
        elif "furnished" in low:
            listing.furnished = text.capitalize()
        elif "term let" in low:
            listing.let_type = "Long term" if low.startswith("long") else "Short term"
        elif "minimum" in low and (m := re.search(r"(\d+)\s*month", low)):
            listing.min_term_months = int(m.group(1))

    listing.bedrooms = pd.get("bedrooms", listing.bedrooms)
    listing.bathrooms = pd.get("bathrooms", listing.bathrooms)
    listing.property_type = pd.get("humanisedPropertyType") or listing.property_type
    feats = [str(f.get("feature", "")).strip() for f in pd.get("features") or [] if isinstance(f, dict)]
    listing.key_features = [f for f in feats if f] or listing.key_features
    listing.description = html_to_text(pd.get("description")) or listing.description
    listing.headline = next((f for f in listing.key_features if not f.lower().startswith("viewings")), listing.headline)
    listing.has_detail = True
    return listing


# ── the adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

class OnTheMarket:
    name = "onthemarket"

    def __init__(self, throttle: Throttle | None = None, max_pages: int = MAX_PAGES):
        self.throttle = throttle or Throttle(min_delay=3.0, jitter=2.0)      # a gentler pace than Rightmove's: an outcode is up to 28 pages
        self.max_pages = max_pages

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return await polite_get(client, self.throttle, url, site="OnTheMarket", referer=f"{BASE}/", **kwargs)

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        """OnTheMarket addresses an outcode by its lower-case name; whether it exists is confirmed by the first search."""
        return outcode.lower() if OUTCODE_RE.match(outcode) else None

    async def search(self, client: httpx.AsyncClient, location_id: str,
                     filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        """Every current listing for the outcode. `filters` is unused: robots.txt forbids the filter parameters, so the
        caller applies the filters to what this yields."""
        seen: set[str] = set()
        page, pages = 1, 1
        while page <= pages and page <= self.max_pages:
            params = {"page": page} if page > 1 else None
            try:
                r = await self._get(client, f"{BASE}/to-rent/property/{location_id}/", params=params)
            except NotFound:
                if page == 1:
                    raise
                break
            data = extract_next_data(r.text)
            if data is None:
                raise Blocked("OnTheMarket search page had no embedded data (layout changed or challenge)")
            items, pages, shown = search_page_info(data)
            if shown and shown != location_id:
                raise NotFound(f"OnTheMarket has no area page for {location_id}")
            for p in items:
                pid = str(p.get("id") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                yield listing_from_search_item(p, default_outcode=location_id.upper())
            page += 1

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        r = await self._get(client, listing.url)
        pd = parse_detail(r.text)
        if pd is None:
            raise Blocked("OnTheMarket advert page had no embedded data (layout changed or challenge)")
        return apply_detail(listing, pd)
