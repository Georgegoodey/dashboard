"""Foxtons adapter (plain HTTP, no browser). Foxtons is a London letting agent, so this is its own stock only.

Findings from looking at the live site and its robots.txt:
- `/properties-to-rent/<outcode>` is a Next.js page: the results are embedded as JSON in `__NEXT_DATA__`
  (`pageProps.pageData.data`), 20 a page with `total`, `page` and `totalPages`; `?page=N` for the rest.
- robots.txt disallows the `?radius=`, `?order_by=`, `?prop_type=` and `?expand=` parameters and the `*/bedroom/*` paths, so
  only the plain outcode page and `page` are requested, and the search filters are applied by the caller.
- An outcode Foxtons does not know gets a regional page of mixed results instead of an error (its `searchedText` then names
  the region), and a removed advert redirects to its outcode's search page. Both are detected from the page data.
- Advert pages hold the full postcode, coordinates, floor area and garden details. Their description is not in the page data.
- `pricePcm` is the monthly rent; `priceFrom` is the same rent per week.
"""
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from app.core.errors import InvalidInput
from app.pipeline.normalise import OUTCODE_RE, normalise_postcode
from app.sources.base import Blocked, NotFound, RawListing, SearchFilters, Throttle
from app.sources.http import polite_get
from app.sources.rightmove import extract_next_data

BASE = "https://www.foxtons.co.uk"
MAX_PAGES = 40
_TYPES = {"flats": "Flat", "flat": "Flat", "houses": "House", "house": "House"}


# ── parsing (pure functions, unit-tested against saved fixtures) ─────────────────────────────────────────────────

def _page_props(html: str) -> dict:
    data = extract_next_data(html)
    props = ((data or {}).get("props") or {}).get("pageProps")
    return props if isinstance(props, dict) else {}


def search_page_info(html: str) -> tuple[list[dict], int, str]:
    """(result items, number of pages, what the page was searched for) from a search page."""
    data = ((_page_props(html).get("pageData") or {}).get("data")) or {}
    return list(data.get("data") or []), int(data.get("totalPages") or 0), str(data.get("searchedText") or "")


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except ArithmeticError:
        return None


def listing_from_search_item(p: dict) -> RawListing | None:
    """A RawListing from one result, or None for something that is not a letting."""
    ref = str(p.get("propertyReference") or "").lower()
    outcode = str(p.get("postcodeShort") or "").upper() or None
    if not ref or p.get("instructionType") != "letting":
        return None
    street, area = (p.get("streetName") or "").strip(), (p.get("locationName") or "").strip()
    parts = [street] + ([area] if area and area.lower() not in street.lower() else [])
    loc = p.get("location") or {}
    pcm = _money(p.get("pricePcm"))
    flags = ("isReduced", "isNewHome", "isUnderOffer", "isRecentLet", "isPrs")
    return RawListing(
        source="foxtons",
        source_listing_id=ref,
        url=f"{BASE}/properties-to-rent/{outcode or 'london'}/{ref}",
        address=", ".join(x for x in [*parts, outcode] if x),
        outcode=outcode,
        lat=loc.get("lat"),
        lon=loc.get("lon"),
        bedrooms=p.get("bedrooms"),
        bathrooms=p.get("bathrooms"),
        property_type=_TYPES.get(str(p.get("typeGroup") or p.get("searchPropertyType") or "").lower()),
        rent_pcm=pcm,
        rent_pw=_money(p.get("priceFrom")),
        agent_name=f'Foxtons, {p["officeName"]}' if p.get("officeName") else "Foxtons",
        raw={k: p.get(k) for k in flags if p.get(k)},
    )


def parse_detail(html: str) -> dict | None:
    """The `propertyDetail` object from an advert page, or None if the page has no usable payload."""
    detail = _page_props(html).get("propertyDetail")
    return detail if isinstance(detail, dict) and detail.get("propertyReference") else None


def apply_detail(listing: RawListing, pd: dict) -> RawListing:
    """Fill a search-level listing with what only the advert page knows."""
    postcode = normalise_postcode((pd.get("postcode") or {}).get("name"))
    if postcode:
        listing.postcode, listing.outcode = postcode, postcode.split()[0]
    if pd.get("lat") is not None and pd.get("lng") is not None:
        listing.lat, listing.lon = pd["lat"], pd["lng"]
    listing.bedrooms = pd.get("bedrooms", listing.bedrooms)
    listing.bathrooms = pd.get("bathrooms", listing.bathrooms)
    listing.property_type = _TYPES.get(str(pd.get("type") or "").lower(), listing.property_type)
    features: list[str] = []
    if pd.get("floorArea"):
        features.append(f"{round(pd['floorArea'])} sq ft floor area")        # the page's figure is in square feet
    for key, noun in (("garden", "garden"), ("garage", "garage")):
        value = str(pd.get(key) or "NONE").upper()
        if value != "NONE":
            features.append(noun.capitalize() if value in ("YES", "TRUE") else f"{value.capitalize()} {noun}")
    extras = (("hasBalcony", "Balcony"), ("hasPatio", "Patio"), ("hasRoofTerrace", "Roof terrace"))
    features += [name for flag, name in extras if pd.get(flag)]
    if pd.get("landlordAcceptZeroDeposit"):
        features.append("Landlord accepts zero deposit")
    listing.key_features = features
    listing.headline = features[0] if features else listing.headline
    listing.has_detail = True
    return listing


# ── the adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

class Foxtons:
    name = "foxtons"

    def __init__(self, throttle: Throttle | None = None, max_pages: int = MAX_PAGES):
        self.throttle = throttle or Throttle(min_delay=3.0, jitter=2.0)
        self.max_pages = max_pages

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return await polite_get(client, self.throttle, url, site="Foxtons", referer=f"{BASE}/", **kwargs)

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        """Foxtons addresses an outcode by its lower-case name; outcodes it does not cover simply have no results."""
        return outcode.lower() if OUTCODE_RE.match(outcode) else None

    async def search(self, client: httpx.AsyncClient, location_id: str,
                     filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        """Every current letting in the outcode. `filters` is unused: the caller applies the search filters."""
        if not OUTCODE_RE.match(location_id):
            raise InvalidInput(f"{location_id!r} is not an outcode")
        seen: set[str] = set()
        page, pages = 1, 1
        while page <= pages and page <= self.max_pages:
            r = await self._get(client, f"{BASE}/properties-to-rent/{location_id}", params={"page": page} if page > 1 else None)
            if "__NEXT_DATA__" not in r.text:
                raise Blocked("Foxtons search page had no embedded data (layout changed or challenge)")
            items, pages, searched = search_page_info(r.text)
            if searched.upper() != location_id.upper():
                raise NotFound(f"Foxtons has no page for {location_id}")
            for p in items:
                item = listing_from_search_item(p)
                if item and item.outcode == location_id.upper() and item.source_listing_id not in seen:
                    seen.add(item.source_listing_id)
                    yield item
            page += 1

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        r = await self._get(client, listing.url)
        pd = parse_detail(r.text)
        if pd is None:
            if _page_props(r.text).get("isSearchPage"):
                raise NotFound(listing.url)                    # a removed advert redirects to its outcode's search page
            raise Blocked("Foxtons advert page had no embedded data (layout changed or challenge)")
        return apply_detail(listing, pd)
