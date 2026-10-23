"""Rightmove adapter (plain HTTP, no browser).

Findings from the phase-0 spike:
- Search pages embed their results as JSON in a `__NEXT_DATA__` script tag: 25 results a page, offsets of 24.
- Detail pages embed `window.__PAGE_MODEL`, whose "data" is a flattened, index-referenced array (devalue style).
  That is where the exact postcode, deposit, furnished status, let type and full description live.
- Search is capped at about 1,050 results (42 pages) per location, so searches are per outcode.
"""
import json
import re
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.pipeline.normalise import OUTCODE_RE, normalise_postcode, parse_date, parse_iso_datetime, pcm_from
from app.sources.base import Blocked, RawListing, SearchFilters, Throttle
from app.sources.http import polite_get

BASE = "https://www.rightmove.co.uk"
PAGE_SIZE = 24
MAX_PAGES = 42


# ── parsing (pure functions, unit-tested against saved fixtures) ─────────────────────────────────────────────────

def extract_next_data(html: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def _find(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find(v, key)
            if found is not None:
                return found
    return None


def search_page_info(data: dict) -> tuple[list[dict], int | None, list[int]]:
    """(property dicts, resultCount, page offsets) from a parsed search page."""
    props = _find(data, "properties") or []
    count = _find(data, "resultCount")
    pagination = _find(data, "pagination") or {}
    offsets = [int(o["value"]) for o in pagination.get("options", []) if str(o.get("value", "")).isdigit()]
    return props, int(count) if str(count or "").isdigit() else None, offsets


def _clean_address(address: str | None) -> str:
    """Adverts put line breaks in the address; keep it on one line."""
    return re.sub(r"\s*[\r\n]+\s*", ", ", (address or "").strip())


def _outcode_from(address: str | None) -> str | None:
    tail = (address or "").replace(",", " ").split()
    for token in reversed(tail[-3:]):
        if OUTCODE_RE.match(token):
            return token.upper()
    return None


def listing_from_search_item(p: dict) -> RawListing:
    price = p.get("price") or {}
    pcm, pw = pcm_from(price.get("amount"), price.get("frequency"))
    loc = p.get("location") or {}
    pid = str(p["id"])
    customer = p.get("customer") or {}
    return RawListing(
        source="rightmove",
        source_listing_id=pid,
        url=f"{BASE}/properties/{pid}",
        address=_clean_address(p.get("displayAddress")),
        outcode=_outcode_from(p.get("displayAddress")),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        bedrooms=p.get("bedrooms"),
        bathrooms=p.get("bathrooms"),
        property_type=p.get("propertySubType") or p.get("propertyTypeFullDescription"),
        rent_pcm=pcm,
        rent_pw=pw,
        available_from=parse_date(p.get("letAvailableDate")),
        agent_name=customer.get("branchDisplayName"),
        description=p.get("summary"),
        first_listed=parse_iso_datetime(p.get("firstVisibleDate")),
        raw={"price": price, "listingUpdate": p.get("listingUpdate"), "displayStatus": p.get("displayStatus"),
             "addedOrReduced": p.get("addedOrReduced")},
    )


def extract_json_object(html: str, marker: str) -> dict | None:
    """The JSON object that follows `marker` (string-aware brace matching)."""
    i = html.find(marker)
    if i < 0:
        return None
    start = html.find("{", i)
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(start, len(html)):
        ch = html[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parsed: dict[Any, Any] = json.loads(html[start:j + 1])
                return parsed
    return None


def unflatten(arr: list) -> Any:
    """Decode a devalue-style flattened array: element 0 is the root and integers inside containers are indexes."""
    memo: dict[int, Any] = {}

    def hydrate(i: int) -> Any:
        if i == -1:
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("Date", "Set", "Map", "BigInt", "Reactive", "null", "Object"):
                memo[i] = v[1] if len(v) > 1 else None
                return memo[i]
            out: list = []
            memo[i] = out
            out.extend(hydrate(x) if isinstance(x, int) else x for x in v)
            return out
        if isinstance(v, dict):
            d: dict = {}
            memo[i] = d
            for k, ref in v.items():
                d[k] = hydrate(ref) if isinstance(ref, int) else ref
            return d
        memo[i] = v
        return v

    return hydrate(0)


def parse_detail(html: str) -> dict | None:
    """The `propertyData` object from a detail page, or None if the page has no usable payload."""
    outer = extract_json_object(html, "window.__PAGE_MODEL")
    if not outer or "data" not in outer:
        return None
    root = unflatten(json.loads(outer["data"]))
    return root.get("propertyData") if isinstance(root, dict) else None


def _plain(html_text: str | None) -> str | None:
    if not html_text:
        return None
    text = HTMLParser(html_text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")).text(separator="\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def apply_detail(listing: RawListing, pd: dict) -> RawListing:
    """Fill a search-level listing with what only the detail page knows."""
    addr = pd.get("address") or {}
    outcode, incode = addr.get("outcode"), addr.get("incode")
    if outcode and incode:
        listing.postcode = normalise_postcode(f"{outcode} {incode}")
        listing.outcode = outcode.upper()
    if addr.get("displayAddress"):
        listing.address = _clean_address(addr["displayAddress"])

    loc = pd.get("location") or {}
    if loc.get("latitude") is not None:
        listing.lat, listing.lon = loc["latitude"], loc["longitude"]

    lettings = pd.get("lettings") or {}
    deposit = lettings.get("deposit")
    listing.deposit = Decimal(str(deposit)) if deposit else None        # 0 means "not stated"
    listing.furnished = (lettings.get("furnishType") or None) and str(lettings["furnishType"]).strip().capitalize()
    listing.let_type = lettings.get("letType") or None
    listing.min_term_months = lettings.get("minimumTermInMonths") or None
    listing.available_from = parse_date(lettings.get("letAvailableDate")) or listing.available_from

    listing.bedrooms = pd.get("bedrooms", listing.bedrooms)
    listing.bathrooms = pd.get("bathrooms", listing.bathrooms)
    listing.property_type = pd.get("propertySubType") or listing.property_type
    customer = pd.get("customer") or {}
    listing.agent_name = customer.get("branchDisplayName") or listing.agent_name
    listing.key_features = [str(x) for x in (pd.get("keyFeatures") or [])]
    listing.description = _plain((pd.get("text") or {}).get("description")) or listing.description
    listing.headline = (listing.key_features[0] if listing.key_features else None) or listing.headline
    listing.has_detail = True
    return listing


def search_params(location_id: str, offset: int, filters: SearchFilters | None = None) -> dict:
    """Query string for a rental search page. Rightmove's maxPrice for rentals is pounds per calendar month."""
    params: dict = {"locationIdentifier": location_id, "radius": "0.0", "channel": "RENT",
                    "index": offset, "sortType": 6, "viewType": "LIST"}
    if filters:
        if filters.min_bedrooms is not None:
            params["minBedrooms"] = filters.min_bedrooms
        if filters.max_bedrooms is not None:
            params["maxBedrooms"] = filters.max_bedrooms
        if filters.max_rent is not None:
            params["maxPrice"] = filters.max_rent
    return params


# ── the adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

class Rightmove:
    name = "rightmove"

    def __init__(self, throttle: Throttle | None = None, max_pages: int = MAX_PAGES):
        self.throttle = throttle or Throttle(min_delay=2.0, jitter=2.0)  # the guide advises 2 to 5 seconds
        self.max_pages = max_pages

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return await polite_get(client, self.throttle, url, site="Rightmove", referer=f"{BASE}/", **kwargs)

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        r = await self._get(client, "https://los.rightmove.co.uk/typeahead",
                            params={"query": outcode, "limit": 5}, headers={"Accept": "application/json"})
        for m in r.json().get("matches", []):
            if m.get("type") == "OUTCODE" and str(m.get("displayName", "")).upper() == outcode.upper():
                return f'OUTCODE^{m["id"]}'
        return None

    async def search(self, client: httpx.AsyncClient, location_id: str,
                     filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        seen: set[str] = set()
        offsets: list[int] = [0]
        i = 0
        while i < len(offsets) and i < self.max_pages:
            params = search_params(location_id, offsets[i], filters)
            r = await self._get(client, f"{BASE}/property-to-rent/find.html", params=params)
            data = extract_next_data(r.text)
            if data is None:
                raise Blocked("Rightmove search page had no embedded data (layout changed or challenge)")
            props, _count, page_offsets = search_page_info(data)
            if i == 0 and page_offsets:
                offsets = page_offsets
            for p in props:
                pid = str(p.get("id"))
                if pid in seen or not p.get("id"):
                    continue
                seen.add(pid)
                yield listing_from_search_item(p)
            i += 1

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        r = await self._get(client, listing.url)
        pd = parse_detail(r.text)
        if pd is None:
            raise Blocked("Rightmove detail page had no embedded data (layout changed or challenge)")
        return apply_detail(listing, pd)
