"""The portal-independent scrape and detail jobs, run against a real database with a fake portal."""
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.db.database import Database
from app.jobs import tasks
from app.repositories import areas
from app.runtime import Runtime
from app.services import filters
from app.sources.base import Blocked, Incomplete, NotFound, RawListing, SearchFilters

pytestmark = pytest.mark.integration


def listing(pid: str, rent: str = "2000", beds: int = 2, outcode: str = "SW11") -> RawListing:
    return RawListing(source="openrent", source_listing_id=pid, url=f"https://example.test/{pid}", address=f"{pid} Road, {outcode}",
                      outcode=outcode, lat=51.47, lon=-0.17, bedrooms=beds, rent_pcm=Decimal(rent))


class FakePortal:
    name = "openrent"

    def __init__(self, items: list[RawListing]) -> None:
        self.items = items
        self.resolved: list[str] = []
        self.missing_area = False
        self.gone: set[str] = set()

    async def resolve_area(self, client: httpx.AsyncClient, outcode: str) -> str | None:
        self.resolved.append(outcode)
        return outcode.lower()

    async def search(self, client: httpx.AsyncClient, location_id: str, filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        if self.missing_area:
            raise NotFound(location_id)
        for item in self.items:
            yield item

    async def fetch_detail(self, client: httpx.AsyncClient, item: RawListing) -> RawListing:
        if item.source_listing_id in self.gone:
            raise NotFound(item.url)
        item.deposit, item.furnished, item.description, item.postcode, item.has_detail = Decimal("1500"), "Furnished", "Lovely.", "SW11 7FD", True
        return item


def runtime(settings: Settings, db: Database, portal: FakePortal) -> Runtime:
    rt = Runtime(settings, db)
    rt.sources = {"openrent": portal}
    return rt


async def test_a_second_portal_is_searched_filtered_stored_and_withdrawn(settings: Settings, db: Database) -> None:
    areas.upsert(db, "SW11", "Battersea", True)
    filters.update(db, SearchFilters(min_bedrooms=1, max_bedrooms=4, max_rent=3500))
    portal = FakePortal([listing("1"), listing("2", rent="9000"), listing("3", beds=6)])      # 2 and 3 break the filters
    rt = runtime(settings, db, portal)

    stats = await tasks.scrape_source(rt, "openrent")
    assert stats["new"] == 1 and stats["filtered_out"] == 2 and stats["areas"] == 1 and not stats["errors"]
    assert db.fetch_all("SELECT s.name FROM listings l JOIN sources s ON s.id = l.source_id") == [{"name": "openrent"}]
    assert areas.list_enabled(db)[0]["source_ids"] == {"openrent": "sw11"}
    assert portal.resolved == ["SW11"]

    portal.items[0].rent_pcm = Decimal("2100")
    stats = await tasks.scrape_source(rt, "openrent")
    assert stats["new"] == 0 and stats["repriced"] == 1 and portal.resolved == ["SW11"]        # the area id is remembered

    portal.items = []                                                                          # gone from the portal
    for _ in range(3):
        stats = await tasks.scrape_source(rt, "openrent")
    assert stats["withdrawn"] == 1
    assert db.fetch_one("SELECT status FROM listings") == {"status": "withdrawn"}


async def test_a_stopped_scrape_resumes_with_the_areas_that_waited_longest(settings: Settings, db: Database) -> None:
    for code in ("KT1", "KT2", "KT3"):
        areas.upsert(db, code, code, True)
    portal = FakePortal([listing("1")])
    searched: list[str] = []
    real = portal.search

    async def blocking(client: httpx.AsyncClient, location_id: str, filters: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        searched.append(location_id)
        if len(searched) == 2:
            raise Blocked("HTTP 429")                          # the second area is where the portal pushes back
        async for item in real(client, location_id, filters):
            yield item

    portal.search = blocking  # type: ignore[method-assign]
    rt = runtime(settings, db, portal)
    stats = await tasks.scrape_source(rt, "openrent")
    assert searched == ["kt1", "kt2"] and "blocked" in stats and stats["areas"] == 1
    searched.clear()
    portal.search = real  # type: ignore[method-assign]
    assert [a["outcode"] for a in areas.list_enabled(db, "openrent")] == ["KT2", "KT3", "KT1"]      # KT1 is done, the rest wait
    assert [a["outcode"] for a in areas.list_enabled(db)] == ["KT1", "KT2", "KT3"]                  # no source: by name


async def test_a_sample_only_portal_never_withdraws_by_absence_but_by_age(settings: Settings, db: Database) -> None:
    areas.upsert(db, "SW11", "Battersea", True)
    filters.update(db, SearchFilters(min_bedrooms=1, max_bedrooms=4, max_rent=3500))
    portal = FakePortal([listing("1"), listing("2")])
    real = portal.search

    async def sample(client: httpx.AsyncClient, location_id: str, flt: SearchFilters | None = None) -> AsyncIterator[RawListing]:
        async for item in real(client, location_id, flt):
            yield item
        raise Incomplete("only a sample")

    portal.search = sample  # type: ignore[method-assign, assignment]
    rt = runtime(settings, db, portal)
    stats = await tasks.scrape_source(rt, "openrent")
    assert stats["new"] == 2 and stats["areas"] == 1 and stats["note"] == "only a sample" and not stats["errors"]

    portal.items = [portal.items[0]]                                                   # listing 2 is no longer shown
    for _ in range(4):
        stats = await tasks.scrape_source(rt, "openrent")
    assert stats["withdrawn"] == 0                                                     # absence from a sample proves nothing
    assert db.fetch_one("SELECT count(*) AS n FROM listings WHERE status = 'active'") == {"n": 2}

    db.execute("UPDATE listings SET last_seen = now() - interval '15 days' WHERE source_listing_id = '2'")
    stats = await tasks.scrape_source(rt, "openrent")
    assert stats["withdrawn"] == 1                                                     # but one not seen for two weeks is gone
    assert db.fetch_one("SELECT source_listing_id FROM listings WHERE status = 'active'") == {"source_listing_id": "1"}
    assert db.fetch_one("SELECT count(*) AS n FROM listing_price_history WHERE status = 'withdrawn'") == {"n": 1}


async def test_an_area_the_portal_has_no_page_for_is_reported_not_fatal(settings: Settings, db: Database) -> None:
    areas.upsert(db, "SW11", "Battersea", True)
    portal = FakePortal([listing("1")])
    portal.missing_area = True
    stats = await tasks.scrape_source(runtime(settings, db, portal), "openrent")
    assert stats["errors"] == ["SW11: openrent has no listings page for it"] and stats["new"] == 0 and stats["areas"] == 0


async def test_advert_details_are_filled_and_gone_adverts_withdrawn(settings: Settings, db: Database) -> None:
    areas.upsert(db, "SW11", "Battersea", True)
    portal = FakePortal([listing("1"), listing("2")])
    rt = runtime(settings, db, portal)
    await tasks.scrape_source(rt, "openrent")
    portal.gone = {"2"}

    stats = await tasks.details_source(rt, "openrent")
    assert stats["fetched"] == 1 and stats["withdrawn"] == 1 and stats["detail_pending"] == 0
    row = db.fetch_one("SELECT l.deposit, l.furnished, p.postcode FROM listings l JOIN properties p ON p.id = l.property_id "
                       "WHERE l.status = 'active'")
    assert row and row["deposit"] == Decimal("1500.00") and row["furnished"] == "Furnished" and row["postcode"] == "SW11 7FD"


def test_every_portal_has_a_search_and_a_details_job() -> None:
    for name in ("rightmove", "onthemarket", "openrent", "foxtons", "rentola"):
        assert f"scrape_{name}" in tasks.JOBS and f"details_{name}" in tasks.JOBS
    jobs: dict[str, Any] = tasks.JOBS
    assert jobs["scrape_openrent"].title == "OpenRent: search"
