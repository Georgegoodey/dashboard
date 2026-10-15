"""The one interface every listings source implements, so nothing downstream knows which portal a listing came from."""
import asyncio
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

import httpx

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


@dataclass(frozen=True)
class SearchFilters:
    """What the user wants to see. None means no limit. The values here are only the starting point; the live
    values are stored in the database and edited in Settings (see pipeline/filters.py)."""
    min_bedrooms: int | None = 1
    max_bedrooms: int | None = 4
    max_rent: int | None = 3500          # pounds per calendar month

    def as_dict(self) -> dict:
        return {"min_bedrooms": self.min_bedrooms, "max_bedrooms": self.max_bedrooms, "max_rent": self.max_rent}

    def accepts(self, listing: "RawListing") -> bool:
        """Re-check a listing a portal returned; portals can ignore or round a parameter. Unknown values are kept."""
        b = listing.bedrooms
        if b is not None and ((self.min_bedrooms is not None and b < self.min_bedrooms)
                              or (self.max_bedrooms is not None and b > self.max_bedrooms)):
            return False
        r = listing.rent_pcm
        # 1% tolerance: weekly adverts are converted to a monthly figure, and rounding must not drop a borderline home
        return not (r is not None and self.max_rent is not None and r > Decimal(self.max_rent) * Decimal("1.01"))


class Blocked(Exception):
    """The site served a challenge or refused us; stop politely instead of hammering it."""


class NotFound(Exception):
    """The advert page no longer exists (usually: the listing was withdrawn)."""


@dataclass
class RawListing:
    """A listing in the app's own terms. Every source adapter produces these."""
    source: str
    source_listing_id: str
    url: str
    address: str
    postcode: str | None = None
    outcode: str | None = None
    lat: float | None = None
    lon: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    property_type: str | None = None
    rent_pcm: Decimal | None = None
    rent_pw: Decimal | None = None
    deposit: Decimal | None = None
    furnished: str | None = None
    let_type: str | None = None
    min_term_months: int | None = None
    available_from: date | None = None
    agent_name: str | None = None
    headline: str | None = None
    description: str | None = None
    key_features: list[str] = field(default_factory=list)
    first_listed: datetime | None = None
    has_detail: bool = False                    # True once the detail page has been parsed (exact postcode, deposit, ...)
    raw: dict[str, Any] = field(default_factory=dict)


class Source(Protocol):
    name: str

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        """Portal-specific location id for a postcode area, or None if the portal does not know it."""

    def search(self, client: httpx.AsyncClient, location_id: str,
               filters: "SearchFilters | None" = None) -> AsyncIterator[RawListing]:
        """Yield every current listing for the area that matches the filters. Detail fields are absent until fetch_detail."""

    async def fetch_detail(self, client: httpx.AsyncClient, listing: RawListing) -> RawListing:
        """Fetch the advert page and fill in exact postcode, deposit, furnished, description and so on."""


class Throttle:
    """Polite pacing: at least `min_delay` seconds between requests plus random jitter, shared across tasks."""

    def __init__(self, min_delay: float = 2.0, jitter: float = 1.5):
        self.min_delay = min_delay
        self.jitter = jitter
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + self.min_delay + random.uniform(0, self.jitter)  # noqa: S311  (request jitter, not security)


def new_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=BROWSER_HEADERS, follow_redirects=True, timeout=timeout)
