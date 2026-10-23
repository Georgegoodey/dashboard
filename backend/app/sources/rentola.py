"""Rentola adapter (plain HTTP, no browser). Rentola is a UK-wide rental aggregator; only London is used here.

Findings from looking at the live site and its robots.txt (which only blocks `*contact=true`, `/ads-map/` and `/api/events`):
- Search pages are server-rendered with a JSON-LD `SearchResultsPage` holding 21 listings (price, address with postcode,
  coordinates, bedrooms); `?page=N` for the rest. Advert pages (`/listings/<slug>-<id>`) carry a JSON-LD `RealEstateListing`
  with the description, bathrooms and the date posted.
- There are no pages per outcode, only per city: `london` holds listings for every London postcode. The price and bedroom
  filters in the URL are applied by the page's script, not the server, so the caller applies the search filters.
- A search view stops at about 50 pages (roughly 1,000 results) although it reports 10,000. To reach more, the sitemap's
  views by property type and bedrooms are walked as well (see VIEWS). Their results overlap, so listings are de-duplicated.
- Most of what Rentola shows is copied from other portals (Rightmove, PrimeLocation), under the original advert's title.
  Those are skipped, since they are already stored from the portal itself and would appear twice with a slightly different
  address. Rentola's own listings are the ones titled like "2 bedroom flat in London".
- Because the views only show a sample, a listing missing from them proves nothing: the search ends with Incomplete.
"""
import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from app.pipeline.normalise import OUTCODE_RE, POSTCODE_RE, html_to_text, parse_iso_datetime, pcm_from
from app.sources.base import Blocked, Incomplete, NotFound, RawListing, SearchFilters, Throttle
from app.sources.http import polite_get

BASE = "https://rentola.co.uk"
MAX_PAGES = 55
PACE = (4.0, 2.0)
CACHE_SECONDS = 3600
# Views from the sitemap, so that together they reach more of London than one view's 50 pages would.
VIEWS = (*(f"{kind}/{n}-bedroom" for kind in ("flat", "house") for n in (1, 2, 3, 4)), "studio-flat")
# Letters of the postcode areas Rentola's London pages cover
LONDON_AREAS = frozenset(
    {"E", "EC", "N", "NW", "SE", "SW", "W", "WC", "BR", "CR", "DA", "EN", "HA", "IG", "KT", "RM", "SM", "TW", "UB", "WD"})
_ID_RE = re.compile(r"-(p[0-9a-z]+)$")
_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


# ── parsing (pure functions, unit-tested against saved fixtures) ─────────────────────────────────────────────────

def _ld_blocks(html: str) -> list[dict]:
    out = []
    for m in _LD_RE.finditer(html):
        try:
            block = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(block, dict):
            out.append(block)
    return out


def is_copy(name: str) -> bool:
    """True for a listing Rentola copied from another portal, which keeps that portal's title ("... to rent, £950 pcm | X")."""
    low = name.lower()
    return "|" in name or " to rent" in low or low.startswith("property to rent")


def _clean_address(street: str) -> str:
    return re.sub(r",?\s*United Kingdom\s*$", "", street or "").strip()


def _listing(item: dict, url: str) -> RawListing | None:
    offer = item.get("offers") or {}
    thing = offer.get("itemOffered") or {}
    m = _ID_RE.search(url)
    name = str(item.get("name") or "")
    if not m or is_copy(name) or name.lower().startswith("room") or str(thing.get("@type")) == "Room":
        return None
    address = _clean_address((thing.get("address") or {}).get("streetAddress", ""))
    pc = POSTCODE_RE.search(address.upper())
    geo = thing.get("geo") or {}
    price = offer.get("price")
    pcm = Decimal(str(price)) if price not in (None, "") else None
    kind = re.match(r"^(?:\d+ bedrooms? )?(.+?) in ", name, re.I)
    studio = bool(kind and "studio" in kind.group(1).lower())              # Rentola counts a studio as one bedroom
    return RawListing(
        source="rentola",
        source_listing_id=m.group(1),
        url=url,
        address=address,
        postcode=f"{pc.group(1)} {pc.group(2)}" if pc else None,
        outcode=pc.group(1) if pc else None,
        lat=geo.get("latitude"),
        lon=geo.get("longitude"),
        bedrooms=0 if studio else (thing.get("numberOfBedrooms") or {}).get("value"),
        bathrooms=thing.get("numberOfBathroomsTotal"),
        property_type=kind.group(1).capitalize() if kind else None,
        rent_pcm=pcm,
        rent_pw=pcm_from(float(pcm), "monthly")[1] if pcm is not None else None,
        first_listed=parse_iso_datetime(offer.get("validFrom") or item.get("datePosted")),
        raw={"name": name},
    )


def search_page_info(html: str) -> list[RawListing]:
    """Rentola's own listings from a search page (copies of other portals' adverts are left out)."""
    out: list[RawListing] = []
    for block in _ld_blocks(html):
        if block.get("@type") != "SearchResultsPage":
            continue
        for entry in (block.get("mainEntity") or {}).get("itemListElement") or []:
            listing = _listing(entry.get("item") or {}, entry.get("url") or (entry.get("item") or {}).get("url") or "")
            if listing:
                out.append(listing)
    return out


def parse_detail(html: str) -> dict | None:
    """The advert's `RealEstateListing` JSON-LD block, or None if the page has none."""
    return next((b for b in _ld_blocks(html) if b.get("@type") == "RealEstateListing"), None)


def apply_detail(listing: RawListing, ld: dict) -> RawListing:
    """Fill a search-level listing with what only the advert page knows."""
    thing = (ld.get("offers") or {}).get("itemOffered") or {}
    listing.description = html_to_text(ld.get("description")) or listing.description
    listing.first_listed = parse_iso_datetime(ld.get("datePosted")) or listing.first_listed
    if thing.get("numberOfBathroomsTotal") is not None:
        listing.bathrooms = thing["numberOfBathroomsTotal"]
    size = (thing.get("floorSize") or {}).get("value")
    listing.key_features = [f"{round(size)} sq m floor area"] if size else []
    listing.has_detail = True
    return listing


# ── the adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

class Rentola:
    name = "rentola"

    def __init__(self, throttle: Throttle | None = None, max_pages: int = MAX_PAGES, views: tuple[str, ...] = VIEWS):
        self.throttle = throttle or Throttle(min_delay=PACE[0], jitter=PACE[1])
        self.max_pages = max_pages
        self.views = views
        self._lock = asyncio.Lock()
        self._sweep: tuple[float, list[RawListing]] | None = None

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return await polite_get(client, self.throttle, url, site="Rentola", referer=f"{BASE}/", **kwargs)

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        """Only London is covered: the location id is the outcode itself, for outcodes in the postcode areas London uses."""
        area = re.match(r"[A-Za-z]+", outcode)
        return outcode.lower() if OUTCODE_RE.match(outcode) and area and area.group(0).upper() in LONDON_AREAS else None

    async def _london(self, client: httpx.AsyncClient) -> list[RawListing]:
        """Everything Rentola shows for London, walked once and kept for an hour: every outcode is then a filter of it."""
        async with self._lock:
            if self._sweep and time.monotonic() - self._sweep[0] < CACHE_SECONDS:
                return self._sweep[1]
            found: dict[str, RawListing] = {}
            for view in self.views:
                for page in range(1, self.max_pages + 1):
                    try:
                        r = await self._get(client, f"{BASE}/property-to-rent/{view}/london", params={"page": page} if page > 1 else None)
                    except NotFound:
                        if page == 1:
                            raise
                        break                                   # past this view's last page
                    if "SearchResultsPage" not in r.text:
                        raise Blocked("Rentola search page had no result data (layout changed or challenge)")
                    page_items = search_page_info(r.text)
                    for item in page_items:
                        found.setdefault(item.source_listing_id, item)
            self._sweep = (time.monotonic(), list(found.values()))
            return self._sweep[1]

    async def search(self, client: httpx.AsyncClient, location_id: str,
                     filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        """Rentola's own London listings in the outcode. `filters` is unused: the caller applies the search filters."""
        outcode = location_id.upper()
        for item in await self._london(client):
            if item.outcode == outcode:
                yield item
        raise Incomplete("Rentola shows only a sample of its London results, so listings not shown are not counted as withdrawn")

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        r = await self._get(client, listing.url)
        ld = parse_detail(r.text)
        if ld is None:
            raise Blocked("Rentola advert page had no listing data (layout changed or challenge)")
        return apply_detail(listing, ld)
