"""The jobs themselves. Each is idempotent and state-driven (it processes whatever is pending), so a missed run
simply means a bigger batch next time."""
import asyncio
import logging
import time
from datetime import time as dtime

import httpx

from app.db import pg
from app.jobs.runner import JobDef, register
from app.pipeline import enrich, filters as filters_mod, ingest
from app.sources.base import Blocked, NotFound, RawListing, new_client
from app.sources.rightmove import Rightmove

log = logging.getLogger("jobs")

_rightmove = Rightmove()          # one instance, so one shared throttle for search and detail pages


def rightmove() -> Rightmove:
    return _rightmove


async def scrape_rightmove() -> dict:
    """Search every enabled area. New listings are stored straight from the search data; detail pages come later."""
    src = rightmove()
    areas = await asyncio.to_thread(pg.fetch_all, "SELECT * FROM search_areas WHERE enabled ORDER BY outcode")
    stats: dict = {"areas": 0, "seen": 0, "new": 0, "touched": 0, "repriced": 0, "withdrawn": 0, "errors": []}
    if not areas:
        stats["note"] = "No search areas configured: add postcode areas in Settings."
        return stats

    flt = await asyncio.to_thread(filters_mod.load)
    stats["filters"] = flt.as_dict()
    stats["filtered_out"] = 0
    await asyncio.to_thread(filters_mod.apply_to_existing, flt)      # keep stored data consistent with the filters

    async with new_client() as client:
        for area in areas:
            outcode = area["outcode"]
            try:
                loc = (area["source_ids"] or {}).get("rightmove")
                if not loc:
                    loc = await src.resolve_area(client, outcode)
                    if not loc:
                        stats["errors"].append(f"{outcode}: Rightmove does not recognise this outcode")
                        continue
                    await asyncio.to_thread(
                        pg.execute, "UPDATE search_areas SET source_ids = source_ids || %s::jsonb WHERE id = %s",
                        ('{"rightmove": "%s"}' % loc, area["id"]))
            except Blocked as e:
                stats["blocked"] = str(e)
                break
            except httpx.HTTPError as e:
                stats["errors"].append(f"{outcode}: {type(e).__name__}")
                continue

            items: list[RawListing] = []
            complete = False
            try:
                async for item in src.search(client, loc, flt):
                    if flt.accepts(item):
                        items.append(item)
                    else:
                        stats["filtered_out"] += 1        # the portal returned it despite the filter
                complete = True
            except Blocked as e:
                stats["blocked"] = str(e)
            except httpx.HTTPError as e:
                stats["errors"].append(f"{outcode}: {type(e).__name__} after {len(items)} listings")

            known = await asyncio.to_thread(ingest.known_listings, "rightmove", [i.source_listing_id for i in items])
            touch = await asyncio.to_thread(ingest.touch_known, "rightmove", [i for i in items if i.source_listing_id in known])
            for item in items:
                if item.source_listing_id not in known:
                    await asyncio.to_thread(ingest.insert_new, item)
                    stats["new"] += 1
            stats["seen"] += len(items)
            stats["touched"] += touch["touched"]
            stats["repriced"] += touch["repriced"]
            if complete:
                stats["withdrawn"] += await asyncio.to_thread(
                    ingest.mark_missing, "rightmove", outcode, {i.source_listing_id for i in items})
                stats["areas"] += 1
            if "blocked" in stats:
                break

    stats["rows_added"] = stats["new"]
    stats["rows_updated"] = stats["repriced"]
    stats["detail_pending"] = await asyncio.to_thread(ingest.count_pending_details, "rightmove")
    return stats


async def details_rightmove(budget_seconds: int = 240, batch: int = 80) -> dict:
    """Fetch detail pages for listings that lack them, within a time budget. Fills postcode, deposit, furnished, text."""
    src = rightmove()
    deadline = time.monotonic() + budget_seconds
    pending = await asyncio.to_thread(ingest.pending_details, "rightmove", batch)
    stats: dict = {"fetched": 0, "withdrawn": 0, "errors": 0, "pending_before": len(pending)}
    if not pending:
        stats["detail_pending"] = 0
        return stats
    async with new_client() as client:
        for row in pending:
            if time.monotonic() > deadline:
                break
            raw = RawListing(source="rightmove", source_listing_id=row["source_listing_id"], url=row["url"],
                             address=row["address"] or "", outcode=row["outcode"])
            try:
                await src.fetch_detail(client, raw)
            except NotFound:
                await asyncio.to_thread(pg.execute, "UPDATE listings SET status = 'withdrawn' WHERE id = %s", (row["id"],))
                stats["withdrawn"] += 1
                continue
            except Blocked as e:
                stats["blocked"] = str(e)
                break
            except httpx.HTTPError:
                stats["errors"] += 1
                continue
            await asyncio.to_thread(ingest.save_detail, row["id"], raw)
            stats["fetched"] += 1
    stats["rows_updated"] = stats["fetched"]
    stats["detail_pending"] = await asyncio.to_thread(ingest.count_pending_details, "rightmove")
    return stats


async def enrich_pending() -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        stats = await enrich.enrich_pending(client)
    stats["rows_updated"] = stats["properties_updated"]
    return stats


register(JobDef("scrape_rightmove", "Rightmove: search",
                "Searches every enabled postcode area and stores new, repriced and withdrawn listings.",
                scrape_rightmove, 180, dtime(7, 0), dtime(22, 0)))
register(JobDef("details_rightmove", "Rightmove: advert details",
                "Fetches advert pages for new listings (exact postcode, deposit, furnished, description), a few minutes at a time.",
                details_rightmove, 10, dtime(7, 0), dtime(23, 0)))
register(JobDef("enrich_pending", "Enrich: borough and area",
                "Looks up borough and area codes for new postcodes (postcodes.io).",
                enrich_pending, 30))


async def commute_pending() -> dict:
    from app.commute import service
    return await service.compute_pending()


register(JobDef("commute_pending", "Commutes: TfL journeys",
                "Works out public-transport journeys from each property to home and work (morning, evening, weekend).",
                commute_pending, 15))
