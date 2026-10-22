"""The jobs themselves. Each is idempotent and state-driven (it processes whatever is pending), so a missed run
simply means a bigger batch next time. They receive the Runtime and use its database, settings and portal clients."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import time as dtime
from typing import TYPE_CHECKING, Any

import httpx

from app.jobs.runner import JobDef
from app.repositories import areas, listings
from app.services import commute, dedupe, filters, postcodes
from app.sources.base import Blocked, Incomplete, NotFound, RawListing, new_client

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("jobs")

STALE_DAYS = 14        # a listing a sample-only portal has not shown for this long is treated as withdrawn


async def scrape_source(rt: "Runtime", source: str) -> dict[str, Any]:
    """Search every enabled area on one portal. New listings are stored straight from the search data; detail pages come later."""
    src, db = rt.sources[source], rt.db
    area_rows = await asyncio.to_thread(areas.list_enabled, db, source)
    stats: dict[str, Any] = {"areas": 0, "seen": 0, "new": 0, "touched": 0, "repriced": 0, "withdrawn": 0, "errors": []}
    if not area_rows:
        stats["note"] = "No search areas configured: add postcode areas in Settings."
        return stats

    flt = await asyncio.to_thread(filters.load, db)
    stats["filters"] = flt.as_dict()
    stats["filtered_out"] = 0
    stale_check = False
    await asyncio.to_thread(filters.apply, db, flt)      # keep stored data consistent with the filters

    async with new_client() as client:
        for area in area_rows:
            outcode = area["outcode"]
            try:
                loc = (area["source_ids"] or {}).get(source)
                if not loc:
                    loc = await src.resolve_area(client, outcode)
                    if not loc:
                        stats["errors"].append(f"{outcode}: {source} does not recognise this outcode")
                        continue
                    await asyncio.to_thread(areas.save_source_id, db, area["id"], source, loc)
            except Blocked as e:
                stats["blocked"] = str(e)
                break
            except httpx.HTTPError as e:
                stats["errors"].append(f"{outcode}: {type(e).__name__}")
                continue

            items: list[RawListing] = []
            complete = False
            sample_only = False
            try:
                async for item in src.search(client, loc, flt):
                    if flt.accepts(item):
                        items.append(item)
                    else:
                        stats["filtered_out"] += 1        # the portal returned it despite the filter
                complete = True
            except Incomplete as e:
                sample_only = True
                stats["note"] = str(e)
            except Blocked as e:
                stats["blocked"] = str(e)
            except NotFound:
                stats["errors"].append(f"{outcode}: {source} has no listings page for it")
            except httpx.HTTPError as e:
                stats["errors"].append(f"{outcode}: {type(e).__name__} after {len(items)} listings")

            known = await asyncio.to_thread(listings.known_listings, db, source, [i.source_listing_id for i in items])
            touch = await asyncio.to_thread(
                listings.touch_known, db, source, [i for i in items if i.source_listing_id in known])
            for item in items:
                if item.source_listing_id not in known:
                    await asyncio.to_thread(listings.insert_new, db, item)
                    stats["new"] += 1
            stats["seen"] += len(items)
            stats["touched"] += touch["touched"]
            stats["repriced"] += touch["repriced"]
            if complete:
                stats["withdrawn"] += await asyncio.to_thread(
                    listings.mark_missing, db, source, outcode, {i.source_listing_id for i in items})
                stats["areas"] += 1
                await asyncio.to_thread(areas.mark_scraped, db, area["id"], source)
            elif sample_only:
                stats["areas"] += 1
                await asyncio.to_thread(areas.mark_scraped, db, area["id"], source)
                stale_check = True
            if "blocked" in stats:
                break

    if stale_check and "blocked" not in stats:
        stats["withdrawn"] += await asyncio.to_thread(listings.withdraw_stale, db, source, STALE_DAYS)
    stats["rows_added"] = stats["new"]
    stats["rows_updated"] = stats["repriced"]
    stats["detail_pending"] = await asyncio.to_thread(listings.count_pending_details, db, source)
    return stats


async def details_source(rt: "Runtime", source: str, budget_seconds: int = 240, batch: int = 80) -> dict[str, Any]:
    """Fetch advert pages for a portal's listings that lack them, within a time budget. Fills postcode, deposit, furnished, text."""
    src, db = rt.sources[source], rt.db
    deadline = time.monotonic() + budget_seconds
    pending = await asyncio.to_thread(listings.pending_details, db, source, batch)
    stats: dict[str, Any] = {"fetched": 0, "withdrawn": 0, "errors": 0, "pending_before": len(pending)}
    if not pending:
        stats["detail_pending"] = 0
        return stats
    async with new_client() as client:
        for row in pending:
            if time.monotonic() > deadline:
                break
            raw = RawListing(source=source, source_listing_id=row["source_listing_id"], url=row["url"],
                             address=row["address"] or "", outcode=row["outcode"])
            try:
                await src.fetch_detail(client, raw)
            except NotFound:
                await asyncio.to_thread(listings.withdraw, db, row["id"])
                stats["withdrawn"] += 1
                continue
            except Blocked as e:
                stats["blocked"] = str(e)
                break
            except httpx.HTTPError:
                stats["errors"] += 1
                continue
            await asyncio.to_thread(listings.save_detail, db, row["id"], raw)
            stats["fetched"] += 1
    stats["rows_updated"] = stats["fetched"]
    stats["detail_pending"] = await asyncio.to_thread(listings.count_pending_details, db, source)
    return stats


def _scrape(source: str) -> Callable[["Runtime"], Awaitable[dict[str, Any]]]:
    async def run(rt: "Runtime") -> dict[str, Any]:
        return await scrape_source(rt, source)
    return run


def _details(source: str) -> Callable[["Runtime"], Awaitable[dict[str, Any]]]:
    async def run(rt: "Runtime") -> dict[str, Any]:
        return await details_source(rt, source)
    return run


async def enrich_pending(rt: "Runtime") -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        stats: dict[str, Any] = dict(await postcodes.enrich_pending(rt.db, client))
    stats["rows_updated"] = stats["properties_updated"]
    return stats


async def dedupe_properties(rt: "Runtime") -> dict[str, Any]:
    """Find the same home on several portals. Merges them only when automatic merging is on; otherwise reports what it would do."""
    found = await asyncio.to_thread(dedupe.plan, rt.db)
    stats: dict[str, Any] = found.summary()
    if await asyncio.to_thread(dedupe.auto_enabled, rt.db):
        done = await asyncio.to_thread(dedupe.apply, rt.db, found)
        stats.update(done)
        stats["rows_updated"] = done["absorbed"]
    elif found.clusters:
        stats["note"] = f"dry run: {found.absorbed} duplicates would be merged; switch on automatic merging to do it"
    return stats


async def commute_pending(rt: "Runtime") -> dict[str, Any]:
    return await commute.compute_pending(rt.db, tfl_key=rt.settings.tfl_app_key or None, timezone=rt.settings.timezone)


JOBS: dict[str, JobDef] = {j.id: j for j in (
    JobDef("scrape_rightmove", "Rightmove: search",
           "Searches every enabled postcode area and stores new, repriced and withdrawn listings.",
           _scrape("rightmove"), 180, dtime(7, 0), dtime(22, 0)),
    JobDef("details_rightmove", "Rightmove: advert details",
           "Fetches advert pages for new listings (exact postcode, deposit, furnished, description), a few minutes at a time.",
           _details("rightmove"), 10, dtime(7, 0), dtime(23, 0)),
    JobDef("scrape_onthemarket", "OnTheMarket: search",
           "Searches every enabled postcode area on OnTheMarket. Your search filters are applied after the pages are read.",
           _scrape("onthemarket"), 180, dtime(7, 0), dtime(22, 0)),
    JobDef("details_onthemarket", "OnTheMarket: advert details",
           "Fetches OnTheMarket advert pages for new listings (exact postcode, deposit, furnished, description).",
           _details("onthemarket"), 10, dtime(7, 0), dtime(23, 0)),
    JobDef("scrape_openrent", "OpenRent: search",
           "Searches every enabled postcode area on OpenRent (private landlords). Your search filters are applied afterwards.",
           _scrape("openrent"), 180, dtime(7, 0), dtime(22, 0)),
    JobDef("details_openrent", "OpenRent: advert details",
           "Fetches OpenRent advert pages for new listings (deposit, availability, furnishing, description).",
           _details("openrent"), 10, dtime(7, 0), dtime(23, 0)),
    JobDef("scrape_foxtons", "Foxtons: search",
           "Searches every enabled postcode area on Foxtons (a London letting agent). Your search filters are applied afterwards.",
           _scrape("foxtons"), 180, dtime(7, 0), dtime(22, 0)),
    JobDef("details_foxtons", "Foxtons: advert details",
           "Fetches Foxtons advert pages for new listings (exact postcode, floor area, garden).",
           _details("foxtons"), 10, dtime(7, 0), dtime(23, 0)),
    JobDef("scrape_rentola", "Rentola: search",
           "Walks Rentola's London listings (its own, not copies of other portals) and keeps those in your areas. Takes about 45 minutes.",
           _scrape("rentola"), 720, dtime(7, 0), dtime(22, 0)),
    JobDef("details_rentola", "Rentola: advert details",
           "Fetches Rentola advert pages for new listings (description, bathrooms, date posted).",
           _details("rentola"), 10, dtime(7, 0), dtime(23, 0)),
    JobDef("dedupe_properties", "Duplicates: match across sites",
           "Finds the same home advertised on several sites (same bedrooms, within 30 m, identical rent, same street) and merges "
           "them into one, but only once automatic merging is switched on. Until then it only reports what it would merge.",
           dedupe_properties, 30),
    JobDef("enrich_pending", "Enrich: borough and area",
           "Looks up borough and area codes for new postcodes (postcodes.io).",
           enrich_pending, 30),
    JobDef("commute_pending", "Commutes: TfL journeys",
           "Works out the public-transport journeys from each property to your commute points.",
           commute_pending, 15),
)}
