"""Weekly sync job.

Shares the bootstrap pipeline (fetcher, parser, loader, frontier) — just
invoked with a staleness filter instead of a full seed load.

Steps:
  1. Record start time in wg_sync_state.
  2. SPARQL seed diff — enqueue any QID not yet in wg_genres.
  3. Stale-page refresh — enqueue genres whose last_fetched_at is older
     than SYNC_STALENESS_DAYS (default 7).
  4. Drain frontier (same fetch/parse/load loop as bootstrap).
  5. Re-resolve unresolved edges.
  6. Write a wg_snapshots row.
  7. Record finish time.

Run via: ``wiki-genres sync``
Schedule via system cron: ``0 6 * * 0 docker compose run --rm api wiki-genres sync``
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from wiki_genres.config import get_settings
from wiki_genres.crawler.bootstrap import _process_one, BootstrapStats
from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.crawler.frontier import (
    dequeue_batch,
    enqueue_many,
    frontier_size,
)
from wiki_genres.crawler.seeds import SeedEntry, fetch_seeds
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.loader import resolve_edges

logger = structlog.get_logger(__name__)


@dataclass
class SyncStats:
    new_genres_discovered: int = 0
    stale_genres_enqueued: int = 0
    genres_processed: int = 0
    genres_failed: int = 0
    edges_resolved: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


async def run_sync(
    *,
    staleness_days: int | None = None,
    concurrency: int | None = None,
    skip_wikidata: bool = False,
    from_cache: bool = False,
) -> SyncStats:
    """Run the weekly sync job end-to-end."""
    settings = get_settings()
    staleness_days = staleness_days if staleness_days is not None else settings.sync_staleness_days
    concurrency = concurrency or settings.crawler_concurrency
    stats = SyncStats()
    t0 = time.monotonic()

    await apply_migrations()
    await _set_sync_state("last_sync_started_at")

    fetcher = WikiFetcher(from_cache=from_cache)
    try:
        snapshot_id = _snapshot_id()
        await _start_snapshot(snapshot_id)

        # 1. SPARQL seed diff — find QIDs not yet in our DB.
        logger.info("sync_sparql_diff")
        try:
            seeds = await fetch_seeds(fetcher)
            known_qids = await _known_qids()
            new_seeds = [s for s in seeds if s.wikidata_qid not in known_qids]
            stats.new_genres_discovered = len(new_seeds)
            if new_seeds:
                added = await enqueue_many(
                    [s.wikipedia_title for s in new_seeds], reason="sync_new"
                )
                logger.info("sync_new_genres_enqueued", count=added)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync_sparql_diff_failed", error=str(exc))

        # 2. Stale-page refresh.
        stale = await _enqueue_stale(staleness_days)
        stats.stale_genres_enqueued = stale
        logger.info("sync_stale_enqueued", count=stale, staleness_days=staleness_days)

        # 3. Drain the frontier.
        sem = asyncio.Semaphore(concurrency)
        bootstrap_stats = BootstrapStats()  # shared mutable state for _process_one

        while True:
            batch = await dequeue_batch(size=concurrency * 2)
            if not batch:
                if await frontier_size() == 0:
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
                        qid_hint=None,
                        stats=bootstrap_stats,
                    )
                )
                for item in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            logger.info(
                "sync_progress",
                processed=bootstrap_stats.genres_processed,
                failed=bootstrap_stats.genres_failed,
                frontier=await frontier_size(),
            )

        stats.genres_processed = bootstrap_stats.genres_processed
        stats.genres_failed = bootstrap_stats.genres_failed
        stats.errors = bootstrap_stats.errors

        # 4. Re-resolve unresolved edges.
        logger.info("sync_resolving_edges")
        stats.edges_resolved = await resolve_edges()

        await _finish_snapshot(snapshot_id, stats)

    finally:
        await fetcher.aclose()

    stats.elapsed_seconds = time.monotonic() - t0
    await _set_sync_state("last_sync_finished_at")

    logger.info(
        "sync_complete",
        new_genres=stats.new_genres_discovered,
        stale_enqueued=stats.stale_genres_enqueued,
        processed=stats.genres_processed,
        failed=stats.genres_failed,
        edges_resolved=stats.edges_resolved,
        elapsed_s=round(stats.elapsed_seconds, 1),
    )
    return stats


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

async def _known_qids() -> set[str]:
    """Return the set of Wikidata QIDs already in wg_genres."""
    engine = get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT wikidata_qid FROM wg_genres WHERE wikidata_qid IS NOT NULL")
        )
        return {row[0] for row in rows}


async def _enqueue_stale(staleness_days: int) -> int:
    """Enqueue genres not fetched in the last staleness_days days."""
    engine = get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                SELECT wikipedia_title FROM wg_genres
                WHERE last_fetched_at < now() - (interval '1 day' * :days)
                  AND wikipedia_title NOT IN (SELECT title FROM wg_frontier)
            """),
            {"days": staleness_days},
        )
        titles = [row[0] for row in rows]

    if not titles:
        return 0
    return await enqueue_many(titles, reason="sync_stale")


async def _set_sync_state(key: str) -> None:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO wg_sync_state (key, value, updated_at)
                VALUES (:key, :value, now())
                ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()
            """),
            {"key": key, "value": f'"{now_iso}"'},
        )


def _snapshot_id() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "-sync"


async def _start_snapshot(snapshot_id: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO wg_snapshots (id, kind, started_at)
                VALUES (:id, 'sync', now())
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": snapshot_id},
        )


async def _finish_snapshot(snapshot_id: str, stats: SyncStats) -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        nodes = await conn.scalar(text("SELECT count(*) FROM wg_genres"))
        edges = await conn.scalar(text("SELECT count(*) FROM wg_edges"))

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE wg_snapshots
                SET finished_at = now(), nodes_total = :nodes, edges_total = :edges,
                    notes = :notes
                WHERE id = :id
            """),
            {
                "id": snapshot_id,
                "nodes": nodes,
                "edges": edges,
                "notes": (
                    f"new={stats.new_genres_discovered} "
                    f"stale_enqueued={stats.stale_genres_enqueued} "
                    f"processed={stats.genres_processed} "
                    f"failed={stats.genres_failed} "
                    f"edges_resolved={stats.edges_resolved}"
                ),
            },
        )
