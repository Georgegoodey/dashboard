"""Polite page fetching shared by the portal adapters: pacing, retries, and a clear signal when a site pushes back."""
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.sources.base import Blocked, NotFound, Throttle


class _Retryable(Exception):
    pass


async def polite_get(client: httpx.AsyncClient, throttle: Throttle, url: str, *, site: str, referer: str,
                     **kwargs: Any) -> httpx.Response:
    """GET one page at the throttle's pace.

    Raises Blocked for a challenge page or HTTP 403/429 (callers stop, they do not retry), NotFound for 404/410, and
    retries network errors and 5xx a few times with backoff.
    """
    headers = {"Referer": referer, **kwargs.pop("headers", {})}
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.TransportError, _Retryable)),
        stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30), reraise=True,
    ):
        with attempt:
            await throttle.wait()
            r = await client.get(url, headers=headers, **kwargs)
            if r.status_code in (403, 429) or "Just a moment" in r.text[:2000]:
                wait = r.headers.get("Retry-After")
                raise Blocked(f"{site} challenged or refused the request (HTTP {r.status_code}"
                              + (f", asks to wait {wait}s)" if wait else ")"))
            if r.status_code in (404, 410):
                raise NotFound(url)
            if r.status_code >= 500:
                raise _Retryable(f"HTTP {r.status_code}")
            return r
    raise RuntimeError("unreachable")
