"""Bootstrap pipeline: end-to-end crawl from seeds to a populated database.

Orchestration logic lives here; the individual stages (seed, fetch, parse,
load) are in their respective modules.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import text

from wiki_genres.config import get_settings
from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.crawler.frontier import (
    dequeue_batch,
    enqueue_many,
    frontier_size,
    requeue,
)
from wiki_genres.crawler.seeds import fetch_seeds
from wiki_genres.curation import (
    MANUAL_MUSIC_GENRE_TITLES,
    MUSIC_CATEGORY_MARKERS,
    MUSIC_GENRE_CLASS_QIDS,
)
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.loader import load_genre, load_pageviews, log_fetch, resolve_edges
from wiki_genres.parser.infobox import parse_genre_page
from wiki_genres.parser.types import ParsedGenre, ParsedWikidataEntity
from wiki_genres.parser.wikidata import parse_wikidata_entity

logger = structlog.get_logger(__name__)


@dataclass
class BootstrapStats:
    seeds_loaded: int = 0
    genres_processed: int = 0
    genres_skipped: int = 0
    genres_failed: int = 0
    new_titles_enqueued: int = 0
    edges_resolved: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


async def run_bootstrap(
    *,
    limit: int | None = None,
    single_title: str | None = None,
    from_cache: bool = False,
    concurrency: int | None = None,
    skip_wikidata: bool = False,
) -> BootstrapStats:
    """Full bootstrap. Applies migrations, seeds the frontier, drains it."""
    settings = get_settings()
    stats = BootstrapStats()
    t0 = time.monotonic()

    # 1. Ensure schema is up to date.
    logger.info("applying_migrations")
    await apply_migrations()

    fetcher = WikiFetcher(from_cache=from_cache)
    concurrency = concurrency or settings.crawler_concurrency

    try:
        snapshot_id = _snapshot_id()
        await _start_snapshot(snapshot_id)

        # 2. Seed the frontier.
        if single_title:
            logger.info("bootstrap_single", title=single_title)
            await enqueue_many([single_title], reason="manual")
            stats.seeds_loaded = 1
        else:
            logger.info("fetching_seed_list")
            seeds = await fetch_seeds(fetcher)
            stats.seeds_loaded = len(seeds)
            logger.info("seeds_loaded", count=len(seeds))

            # Filter seeds that are already in the DB (restartable bootstrap).
            new_titles = await _filter_new_titles([s.wikipedia_title for s in seeds])
            enqueued = await enqueue_many(new_titles, reason="seed")
            logger.info("frontier_seeded", enqueued=enqueued, skipped=len(seeds) - enqueued)

            # Pre-populate QID map from seeds so we don't refetch page_props
            # for every seed title.
            _qid_cache: dict[str, str] = {
                s.wikipedia_title: s.wikidata_qid for s in seeds if s.wikidata_qid
            }

        # 3. Process the frontier in batches.
        sem = asyncio.Semaphore(concurrency)
        total_processed = 0

        while True:
            batch = await dequeue_batch(size=concurrency * 2)
            if not batch:
                # Check if we should keep waiting for stragglers.
                remaining = await frontier_size()
                if remaining == 0:
                    break
                await asyncio.sleep(1.0)
                continue

            tasks = [
                asyncio.create_task(
                    _process_one(
                        fetcher=fetcher,
                        title=item["title"],
                        reason=item["reason"],
                        attempts=item["attempts"],
                        sem=sem,
                        skip_wikidata=skip_wikidata,
                        qid_hint=(_qid_cache if not single_title else {}).get(item["title"]),
                        stats=stats,
                    )
                )
                for item in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            total_processed += len(batch)

            if limit and total_processed >= limit:
                logger.info("bootstrap_limit_reached", limit=limit)
                break

            logger.info(
                "bootstrap_progress",
                processed=total_processed,
                frontier=await frontier_size(),
                failed=stats.genres_failed,
            )

        # 4. Resolution pass.
        logger.info("resolving_edges")
        stats.edges_resolved = await resolve_edges()

        await _finish_snapshot(snapshot_id, stats)

    finally:
        await fetcher.aclose()

    stats.elapsed_seconds = time.monotonic() - t0
    logger.info(
        "bootstrap_complete",
        genres=stats.genres_processed,
        failed=stats.genres_failed,
        edges_resolved=stats.edges_resolved,
        elapsed_s=round(stats.elapsed_seconds, 1),
    )
    return stats


async def _process_one(
    fetcher: WikiFetcher,
    title: str,
    reason: str,
    attempts: int,
    sem: asyncio.Semaphore,
    skip_wikidata: bool,
    qid_hint: str | None,
    stats: BootstrapStats,
    triggered_by: str = "bootstrap",
) -> None:
    async with sem:
        try:
            await _fetch_parse_load(
                fetcher=fetcher,
                title=title,
                skip_wikidata=skip_wikidata,
                qid_hint=qid_hint,
                stats=stats,
                triggered_by=triggered_by,
            )
            stats.genres_processed += 1
        except Exception as exc:
            stats.genres_failed += 1
            stats.errors.append(f"{title}: {exc}")
            logger.warning("genre_failed", title=title, error=str(exc))
            await requeue(title, reason, attempts)


async def _fetch_parse_load(
    fetcher: WikiFetcher,
    title: str,
    skip_wikidata: bool,
    qid_hint: str | None,
    stats: BootstrapStats,
    triggered_by: str = "bootstrap",
) -> None:
    logger.debug("processing", title=title)

    # --- Fetch wikitext ---------------------------------------------------
    wikitext_result = await fetcher.fetch_wikitext(title)
    await log_fetch(
        url=wikitext_result.url,
        http_status=wikitext_result.http_status,
        content_sha256=wikitext_result.content_sha256,
        elapsed_ms=wikitext_result.elapsed_ms,
        via="bootstrap",
    )
    if not wikitext_result.ok:
        raise RuntimeError(f"wikitext fetch failed: HTTP {wikitext_result.http_status}")

    wikitext_data = wikitext_result.json()
    parse_block = wikitext_data.get("parse", {})
    wikitext = parse_block.get("wikitext", "")
    upstream_revision = parse_block.get("revid")
    canonical_title = parse_block.get("title", title)

    # Check for redirect (wikitext that's just "#REDIRECT [[Target]]").
    if wikitext.strip().upper().startswith("#REDIRECT"):
        await _handle_redirect(canonical_title, wikitext, stats)
        return

    # --- Fetch page props (QID + categories) if QID not already known ----
    qid = qid_hint
    categories: list[str] = []

    props_result = await fetcher.fetch_page_props(canonical_title)
    if props_result.ok:
        pages = props_result.json().get("query", {}).get("pages", [])
        if pages:
            page = pages[0]
            if qid is None:
                qid = page.get("pageprops", {}).get("wikibase_item")
            revisions = page.get("revisions", [])
            if revisions and upstream_revision is None:
                upstream_revision = revisions[0].get("revid")

    cats_result = await fetcher.fetch_categories(canonical_title)
    if cats_result.ok:
        pages = cats_result.json().get("query", {}).get("pages", [])
        if pages:
            categories = [c.get("title", "") for c in pages[0].get("categories", [])]

    # --- Fetch plain-text summary -----------------------------------------
    summary: str | None = None
    summary_result = await fetcher.fetch_summary(canonical_title)
    if summary_result.ok:
        summary = summary_result.json().get("extract")

    # --- Fetch Wikidata entity ---------------------------------------------
    wikidata_entity = None
    if qid and not skip_wikidata:
        wd_result = await fetcher.fetch_wikidata_entity(qid)
        if wd_result.ok:
            wikidata_entity = parse_wikidata_entity(wd_result.json(), qid)

    # --- Parse infobox ----------------------------------------------------
    parsed = parse_genre_page(
        wikitext=wikitext,
        title=canonical_title,
        summary=summary,
        wikidata_qid=qid,
        upstream_revision=upstream_revision,
        categories=categories,
    )

    # If wikidata provided extra edges, attach them.
    if wikidata_entity:
        parsed.wikidata_edges = wikidata_entity.edges
        # Merge wikidata aliases that aren't already in infobox aliases.
        existing = {a.lower() for a in parsed.aliases}
        for a in wikidata_entity.aliases:
            if a.lower() not in existing:
                parsed.aliases.append(a)
                existing.add(a.lower())

    if not _is_music_genre_candidate(parsed, wikidata_entity):
        stats.genres_skipped += 1
        logger.info("genre_skipped_not_music_genre", title=canonical_title, qid=qid)
        return

    # --- Load to DB -------------------------------------------------------
    genre_id = await load_genre(parsed, wikidata_entity, triggered_by=triggered_by)

    # --- Fetch pageviews --------------------------------------------------
    try:
        pv_result = await fetcher.fetch_pageviews(canonical_title)
        if pv_result.ok:
            pv_items = pv_result.json().get("items", [])
            if pv_items:
                await load_pageviews(genre_id, pv_items)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pageview_fetch_skipped", title=title, error=str(exc))

    # --- Enqueue newly-discovered genre titles ----------------------------
    if parsed.new_genre_titles:
        new = await _filter_new_titles(parsed.new_genre_titles)
        if new:
            added = await enqueue_many(new, reason="wikilink")
            stats.new_titles_enqueued += added


def _is_music_genre_candidate(
    parsed: ParsedGenre,
    wikidata_entity: ParsedWikidataEntity | None,
) -> bool:
    """Return True when a fetched page belongs in the public genre graph."""
    if parsed.has_infobox:
        return True

    if parsed.wikipedia_title in MANUAL_MUSIC_GENRE_TITLES:
        return True

    if wikidata_entity and any(
        edge.source == "wikidata"
        and edge.relation in {"instance_of", "subclass_of"}
        and edge.raw_label in MUSIC_GENRE_CLASS_QIDS
        for edge in wikidata_entity.edges
    ):
        return True

    return any(
        marker in category.lower()
        for category in parsed.categories
        for marker in MUSIC_CATEGORY_MARKERS
    )


async def _handle_redirect(from_title: str, wikitext: str, stats: BootstrapStats) -> None:
    """Record a Wikipedia redirect in ``wg_redirects``."""
    import re

    m = re.search(r"#REDIRECT\s*\[\[([^\]]+)\]\]", wikitext, re.IGNORECASE)
    if not m:
        return
    to_title = m.group(1).split("|")[0].strip()

    engine = get_engine()
    async with engine.begin() as conn:
        # Only insert the redirect if the target genre already exists.
        to_id = await conn.scalar(
            text("select id from wg_genres where wikipedia_title = :t"),
            {"t": to_title},
        )
        if to_id:
            await conn.execute(
                text("""
                    insert into wg_redirects (from_title, to_genre_id, first_seen_at)
                    values (:from, :to, now())
                    on conflict (from_title) do nothing
                """),
                {"from": from_title, "to": to_id},
            )
    stats.genres_skipped += 1


async def _filter_new_titles(titles: list[str]) -> list[str]:
    """Return only titles not yet in ``wg_genres`` or ``wg_frontier``."""
    if not titles:
        return []
    engine = get_engine()
    async with engine.connect() as conn:
        existing_genres = {
            row[0]
            for row in await conn.execute(
                text("select wikipedia_title from wg_genres where wikipedia_title = any(:titles)"),
                {"titles": titles},
            )
        }
        existing_frontier = {
            row[0]
            for row in await conn.execute(
                text("select title from wg_frontier where title = any(:titles)"),
                {"titles": titles},
            )
        }
    return [t for t in titles if t not in existing_genres and t not in existing_frontier]


def _snapshot_id() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "-bootstrap"


async def _start_snapshot(snapshot_id: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                insert into wg_snapshots (id, kind, started_at)
                values (:id, 'bootstrap', now())
                on conflict (id) do nothing
            """),
            {"id": snapshot_id},
        )


async def _finish_snapshot(snapshot_id: str, stats: BootstrapStats) -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        nodes = await conn.scalar(text("select count(*) from wg_genres"))
        edges = await conn.scalar(text("select count(*) from wg_edges"))

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                update wg_snapshots
                set finished_at = now(), nodes_total = :nodes, edges_total = :edges,
                    notes = :notes
                where id = :id
            """),
            {
                "id": snapshot_id,
                "nodes": nodes,
                "edges": edges,
                "notes": (
                    f"processed={stats.genres_processed} "
                    f"failed={stats.genres_failed} "
                    f"edges_resolved={stats.edges_resolved}"
                ),
            },
        )
