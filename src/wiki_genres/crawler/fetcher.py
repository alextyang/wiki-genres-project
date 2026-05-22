"""Async HTTP fetcher for Wikipedia and Wikidata APIs.

Features:
- Shared ``httpx.AsyncClient`` with Wikimedia-compliant ``User-Agent``.
- Per-host rate limiting (one token bucket each for en.wikipedia and wikidata).
- Disk cache under ``settings.crawler_cache_dir``: re-running the bootstrap
  with ``from_cache=True`` never touches the network.
- Every outbound request is logged to ``wg_fetch_log`` via the loader caller
  (this module returns ``FetchResult`` which includes the metadata needed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from wiki_genres.config import get_settings

logger = structlog.get_logger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REST = "https://en.wikipedia.org/api/rest_v1"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIMEDIA_REST = "https://wikimedia.org/api/rest_v1"


@dataclass
class FetchResult:
    url: str
    http_status: int
    content: bytes | None
    elapsed_ms: int
    from_cache: bool
    content_sha256: str | None = None

    def json(self) -> Any:
        if self.content is None:
            return None
        return json.loads(self.content)

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.content is not None


class WikiFetcher:
    """Fetches from Wikipedia and Wikidata with caching and rate limiting."""

    def __init__(self, from_cache: bool = False) -> None:
        settings = get_settings()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": settings.wiki_user_agent},
            follow_redirects=True,
            timeout=30.0,
        )
        self._cache_dir = settings.crawler_cache_dir
        self._interval = settings.crawler_request_interval_ms / 1000.0
        self._from_cache = from_cache
        # Per-host last-request timestamps for rate limiting.
        self._last_request: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {
            "en.wikipedia.org": asyncio.Lock(),
            "www.wikidata.org": asyncio.Lock(),
            "query.wikidata.org": asyncio.Lock(),
            "wikimedia.org": asyncio.Lock(),
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Public fetch methods                                                 #
    # ------------------------------------------------------------------ #

    async def fetch_wikitext(self, title: str) -> FetchResult:
        """Fetch raw wikitext for a Wikipedia article."""
        url = (
            f"{WIKIPEDIA_API}?action=parse&page={quote(title, safe='')}"
            f"&prop=wikitext&formatversion=2&format=json"
        )
        return await self._get(url, host="en.wikipedia.org")

    async def fetch_summary(self, title: str) -> FetchResult:
        """Fetch the plain-text lead summary via the REST v1 API."""
        url = f"{WIKIPEDIA_REST}/page/summary/{quote(title, safe='')}"
        return await self._get(url, host="en.wikipedia.org")

    async def fetch_page_props(self, title: str) -> FetchResult:
        """Fetch page properties (incl. wikibase_item = Wikidata QID)."""
        url = (
            f"{WIKIPEDIA_API}?action=query&prop=pageprops|revisions"
            f"&titles={quote(title, safe='')}&rvprop=ids&formatversion=2&format=json"
        )
        return await self._get(url, host="en.wikipedia.org")

    async def fetch_templates(self, title: str) -> FetchResult:
        """Quick check whether a page transcludes Template:Infobox music genre."""
        url = (
            f"{WIKIPEDIA_API}?action=query&prop=templates"
            f"&tltemplates=Template:Infobox+music+genre"
            f"&titles={quote(title, safe='')}&formatversion=2&format=json"
        )
        return await self._get(url, host="en.wikipedia.org")

    async def fetch_categories(self, title: str) -> FetchResult:
        """Fetch all categories for a page."""
        url = (
            f"{WIKIPEDIA_API}?action=query&prop=categories"
            f"&cllimit=50&titles={quote(title, safe='')}&formatversion=2&format=json"
        )
        return await self._get(url, host="en.wikipedia.org")

    async def fetch_wikidata_entity(self, qid: str) -> FetchResult:
        """Fetch a Wikidata entity by QID."""
        url = (
            f"{WIKIDATA_API}?action=wbgetentities&ids={qid}"
            f"&props=aliases%7Cclaims%7Csitelinks&languages=en&format=json"
        )
        return await self._get(url, host="www.wikidata.org")

    async def fetch_sparql(self, query: str) -> FetchResult:
        """Run a SPARQL query against Wikidata."""
        url = f"{WIKIDATA_SPARQL}?format=json&query={quote(query, safe='')}"
        # SPARQL can take 30–60 s on the public endpoint; use a longer timeout.
        return await self._get(url, host="query.wikidata.org", timeout=90.0)

    async def fetch_pageviews(self, title: str, months_back: int = 12) -> FetchResult:
        """Fetch monthly pageview counts for a Wikipedia article.

        Uses the Wikimedia pageviews API, returning the last *months_back*
        complete months of data.
        """
        from datetime import date

        today = date.today()
        # End = 1st of last complete month.
        if today.month == 1:
            end = date(today.year - 1, 12, 1)
        else:
            end = date(today.year, today.month - 1, 1)

        # Start = months_back months before end (inclusive).
        total = end.year * 12 + (end.month - 1) - (months_back - 1)
        start = date(total // 12, total % 12 + 1, 1)

        encoded = quote(title.replace(" ", "_"), safe="")
        url = (
            f"{WIKIMEDIA_REST}/metrics/pageviews/per-article"
            f"/en.wikipedia.org/all-access/all-agents"
            f"/{encoded}/monthly/{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}"
        )
        return await self._get(url, host="wikimedia.org")

    async def has_music_genre_infobox(self, title: str) -> bool:
        """Return True if the page transcludes Template:Infobox music genre."""
        result = await self.fetch_templates(title)
        if not result.ok:
            return False
        data = result.json()
        pages = data.get("query", {}).get("pages", [])
        for page in pages:
            templates = page.get("templates", [])
            if any(
                t.get("title", "").lower() == "template:infobox music genre"
                for t in templates
            ):
                return True
        return False

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    async def _get(self, url: str, host: str, timeout: float | None = None) -> FetchResult:
        cache_key = _url_cache_key(url)
        cache_path = self._cache_dir / host / f"{cache_key}.json"

        # Attempt cache read.
        if self._from_cache or (cached := _read_cache(cache_path)):
            if self._from_cache:
                cached = _read_cache(cache_path)
            if cached:
                sha = hashlib.sha256(cached).hexdigest()
                logger.debug("cache_hit", url=url)
                return FetchResult(
                    url=url,
                    http_status=200,
                    content=cached,
                    elapsed_ms=0,
                    from_cache=True,
                    content_sha256=sha,
                )

        if self._from_cache:
            # Cache miss with from_cache=True — return empty rather than fetch.
            logger.warning("cache_miss_no_fetch", url=url)
            return FetchResult(url=url, http_status=0, content=None, elapsed_ms=0, from_cache=True)

        # Rate limit per host.
        await self._throttle(host)

        t0 = time.monotonic()
        try:
            resp = await self._client.get(url, timeout=timeout)
            elapsed = int((time.monotonic() - t0) * 1000)
            content = resp.content if resp.status_code == 200 else None
            sha = hashlib.sha256(content).hexdigest() if content else None
            logger.debug(
                "fetched", url=url, status=resp.status_code, elapsed_ms=elapsed
            )
            if content:
                _write_cache(cache_path, content)
            return FetchResult(
                url=url,
                http_status=resp.status_code,
                content=content,
                elapsed_ms=elapsed,
                from_cache=False,
                content_sha256=sha,
            )
        except httpx.RequestError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("fetch_error", url=url, error=str(exc))
            return FetchResult(
                url=url, http_status=0, content=None, elapsed_ms=elapsed, from_cache=False
            )

    async def _throttle(self, host: str) -> None:
        lock = self._host_locks.get(host)
        if lock is None:
            return
        async with lock:
            since_last = time.monotonic() - self._last_request.get(host, 0.0)
            if since_last < self._interval:
                await asyncio.sleep(self._interval - since_last)
            self._last_request[host] = time.monotonic()


# ------------------------------------------------------------------ #
# Cache helpers                                                        #
# ------------------------------------------------------------------ #

def _url_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def _read_cache(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_cache(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
