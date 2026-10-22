"""OpenRent adapter (plain HTTP, no browser).

Findings from looking at the live site and its robots.txt (which only blocks account, affiliate and internal paths):
- A search page, `/properties-to-rent/<outcode>?term=<OUTCODE>`, lists 20 cards as HTML and carries the whole result set
  in script variables: `PROPERTYIDS`, and parallel `PROPERTYLISTLATITUDES` / `PROPERTYLISTLONGITUDES` arrays. More cards
  come with `&skip=20`, `&skip=40`, and so on.
- The search covers a radius around the outcode, so neighbouring outcodes appear too; only listings in the requested
  outcode are kept. The price and bedroom filters in the URL are applied by the page's own script, not the server, so the
  caller applies the search filters to what this yields.
- OpenRent only shows a street and an outcode, never a full postcode. Advert pages hold the deposit, availability,
  minimum tenancy, furnishing, features, full description and the coordinates. A let advert says so and is treated as gone.
- Results are nearest-first, so once two pages in a row hold nothing from the requested outcode the rest is skipped. OpenRent
  answers HTTP 429 to a faster pace than a few requests a minute, so the default pace is slow (see PACE) and a 429 stops the run.
- Rooms in a shared home are skipped: their rent is for a room, which would distort rent comparisons.
"""
import re
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.pipeline.normalise import OUTCODE_RE, html_to_text, parse_date
from app.sources.base import Blocked, NotFound, RawListing, SearchFilters, Throttle
from app.sources.http import polite_get

BASE = "https://www.openrent.co.uk"
PAGE_SIZE = 20
MAX_PAGES = 40
EMPTY_PAGES_TO_STOP = 2
PACE = (5.0, 3.0)          # seconds between requests, plus up to this much jitter: about 8 a minute (2 to 4 s drew a 429)
_TITLE_RE = re.compile(r"^(?P<kind>.+?), (?P<street>.+), (?P<outcode>[A-Z]{1,2}\d[A-Z\d]?)$", re.I)
_BEDS_RE = re.compile(r"^(\d+)\s*Beds?\b", re.I)


# ── parsing (pure functions, unit-tested against saved fixtures) ─────────────────────────────────────────────────

def _array(html: str, name: str) -> list[str]:
    m = re.search(rf"var {name} ?= ?\[([^\]]*)\]", html)
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def _money(text: str | None) -> Decimal | None:
    m = re.search(r"([\d,]+(?:\.\d+)?)", text or "")
    return Decimal(m.group(1).replace(",", "")) if m else None


def search_page_info(html: str) -> tuple[list[RawListing], int, int]:
    """(listings on this page, total results, results per page) from a search page. Rooms in shared homes are left out."""
    ids = _array(html, "PROPERTYIDS")
    lats, lons = _array(html, "PROPERTYLISTLATITUDES"), _array(html, "PROPERTYLISTLONGITUDES")
    where = {pid: (float(lats[i]), float(lons[i])) for i, pid in enumerate(ids) if i < len(lats) and i < len(lons)}
    total_m = re.search(r"var NUMBEROFPROPERTIES ?= ?(\d+)", html)
    total = int(total_m.group(1)) if total_m else len(ids)

    out: list[RawListing] = []
    for card in HTMLParser(html).css("a.search-property-card"):
        href = card.attributes.get("href") or ""
        pid = href.rstrip("/").rsplit("/", 1)[-1]
        title_node = card.css_first("div.fs-3")
        title = re.sub(r"\s+", " ", title_node.text()).strip() if title_node else ""
        m = _TITLE_RE.match(title)
        if not pid.isdigit() or not m or m.group("kind").lower().startswith("room"):
            continue
        facts = [re.sub(r"\s+", " ", li.text()).strip() for li in card.css("ul.list-unstyled li")]
        kind = m.group("kind")
        beds = next((int(b.group(1)) for f in facts if (b := _BEDS_RE.match(f))), None)
        if beds is None and kind.lower().startswith("studio"):
            beds = 0
        baths = next((int(b.group(1)) for f in facts if (b := re.match(r"^(\d+)\s*Baths?\b", f, re.I))), None)
        pcm_node, pw_node = card.css_first(".pim span.fs-4"), card.css_first(".piw span.fs-4")
        pcm = _money(pcm_node.text() if pcm_node else None)
        pw = _money(pw_node.text() if pw_node else None)
        desc = card.css_first(".search-property-description")
        lat, lon = where.get(pid, (None, None))
        out.append(RawListing(
            source="openrent",
            source_listing_id=pid,
            url=f"{BASE}{href}",
            address=f'{m.group("street")}, {m.group("outcode").upper()}',
            outcode=m.group("outcode").upper(),
            lat=lat,
            lon=lon,
            bedrooms=beds,
            bathrooms=baths,
            property_type=re.sub(r"^(\d+\s*Bed|Studio)\s*", "", kind, flags=re.I).strip().capitalize() or None,
            rent_pcm=pcm,
            rent_pw=pw,
            furnished=next((f for f in facts if "furnished" in f.lower()), None),
            description=re.sub(r"\s+", " ", desc.text()).strip() if desc else None,
            headline=title,
            raw={"title": title},
        ))
    return out, total, PAGE_SIZE


def is_let(html: str) -> bool:
    """OpenRent keeps the page of a let advert and says so at the top."""
    return "This property is no longer available for rent" in html


def _rows(tree: HTMLParser) -> dict[str, str | bool]:
    """Label -> value for the detail tables: text where there is some, otherwise whether the row is ticked."""
    rows: dict[str, str | bool] = {}
    for tr in tree.css("table.table-column-2-right tr"):
        cells = tr.css("td")
        if len(cells) < 2 or not cells[0].text(strip=True):
            continue
        label = re.sub(r"\s+", " ", cells[0].text()).strip()
        value = re.sub(r"\s+", " ", cells[-1].text()).strip()
        rows[label] = value if value else "M18 6 6 18" not in (cells[-1].html or "")
    return rows


def apply_detail(listing: RawListing, html: str) -> RawListing:
    """Fill a search-level listing with what only the advert page knows."""
    tree = HTMLParser(html)
    rows = _rows(tree)
    deposit = _money(str(rows.get("Deposit", "")))
    listing.deposit = deposit if deposit else None
    pcm = _money(str(rows.get("Rent PCM", "")))
    if pcm:
        listing.rent_pcm = pcm
    avail = str(rows.get("Available From", "")).strip()
    listing.available_from = parse_date(re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", avail)) if avail else listing.available_from
    tenancy = re.search(r"(\d+)", str(rows.get("Preferred Minimum Tenancy", "")))
    listing.min_term_months = int(tenancy.group(1)) if tenancy else None
    furnishing = str(rows.get("Furnishing", "")).strip()
    listing.furnished = furnishing.capitalize() if furnishing else listing.furnished
    listing.key_features = [label for label, value in rows.items() if value is True]

    m = tree.css_first("#map")
    lat, lng = (m.attributes.get("data-lat"), m.attributes.get("data-lng")) if m is not None else (None, None)
    if lat and lng:
        listing.lat, listing.lon = float(lat), float(lng)
    for li in tree.css("h1 ~ ul li"):
        text = re.sub(r"\s+", " ", li.text()).strip()
        if b := re.match(r"^(\d+) bathrooms?", text, re.I):
            listing.bathrooms = int(b.group(1))
        elif b := re.match(r"^(\d+) bedrooms?", text, re.I):
            listing.bedrooms = int(b.group(1))
    desc = tree.css_first("#descriptionText")
    if desc is not None:
        toggle = desc.css_first("#toggleDescriptionText")      # the "Read more" button sits inside the text
        if toggle is not None:
            toggle.decompose()
        listing.description = html_to_text(desc.html) or listing.description
    listing.has_detail = True
    return listing


# ── the adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

class OpenRent:
    name = "openrent"

    def __init__(self, throttle: Throttle | None = None, max_pages: int = MAX_PAGES):
        self.throttle = throttle or Throttle(min_delay=PACE[0], jitter=PACE[1])
        self.max_pages = max_pages

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return await polite_get(client, self.throttle, url, site="OpenRent", referer=f"{BASE}/", **kwargs)

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        """OpenRent searches by the outcode text, so the lower-case outcode is the location id."""
        return outcode.lower() if OUTCODE_RE.match(outcode) else None

    async def search(self, client: httpx.AsyncClient, location_id: str,
                     filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        """Every current listing in the outcode. `filters` is unused: the caller applies the search filters."""
        outcode = location_id.upper()
        seen: set[str] = set()
        page, pages, empty = 0, 1, 0
        while page < pages and page < self.max_pages and empty < EMPTY_PAGES_TO_STOP:
            params: dict[str, Any] = {"term": outcode}
            if page:
                params["skip"] = page * PAGE_SIZE
            r = await self._get(client, f"{BASE}/properties-to-rent/{location_id}", params=params)
            if "PROPERTYIDS" not in r.text:
                raise Blocked("OpenRent search page had no result data (layout changed or challenge)")
            items, total, per_page = search_page_info(r.text)
            pages = -(-total // per_page)
            here = [i for i in items if not i.outcode or i.outcode == outcode]       # the rest are neighbours, from the radius
            empty = 0 if here or not items else empty + 1
            for item in here:
                if item.source_listing_id not in seen:
                    seen.add(item.source_listing_id)
                    yield item
            page += 1

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        r = await self._get(client, listing.url)
        if is_let(r.text):
            raise NotFound(listing.url)
        if "descriptionText" not in r.text:
            raise Blocked("OpenRent advert page had no description (layout changed or challenge)")
        return apply_detail(listing, r.text)
