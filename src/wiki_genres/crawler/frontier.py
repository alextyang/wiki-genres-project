"""Postgres-backed frontier queue for the bootstrap crawl and sync worker.

The frontier is a persistent queue stored in ``wg_frontier``.  Using Postgres
rather than an in-memory structure means the bootstrap is restartable: if the
process dies mid-crawl, titles already processed are in ``wg_genres``; titles
still pending are in ``wg_frontier``; restarting picks up from where it left off.

Concurrent dequeuing is safe thanks to ``SELECT … FOR UPDATE SKIP LOCKED``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine

logger = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = [60, 300, 900]  # 1 min, 5 min, 15 min


async def enqueue_many(titles: list[str], reason: str) -> int:
    """Insert titles that are not already in the frontier. Returns count added."""
    if not titles:
        return 0
    engine = get_engine()
    added = 0
    async with engine.begin() as conn:
        for title in titles:
            result = await conn.execute(
                text("""
                    insert into wg_frontier (title, reason, enqueued_at, not_before)
                    values (:title, :reason, now(), now())
                    on conflict (title) do nothing
                """),
                {"title": title, "reason": reason},
            )
            added += result.rowcount
    logger.debug("enqueued", count=added, reason=reason)
    return added


async def enqueue_one(title: str, reason: str) -> bool:
    """Enqueue a single title. Returns True if it was newly added."""
    return (await enqueue_many([title], reason)) == 1


async def dequeue_batch(size: int = 20) -> list[dict]:
    """Dequeue up to ``size`` titles that are ready (not_before ≤ now).

    Removes the rows atomically so parallel workers don't double-process.
    Returns a list of ``{"title": ..., "reason": ..., "attempts": ...}`` dicts.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(
            text("""
                delete from wg_frontier
                where title in (
                    select title from wg_frontier
                    where not_before <= now()
                    order by enqueued_at
                    limit :size
                    for update skip locked
                )
                returning title, reason, attempts
            """),
            {"size": size},
        )
        return [dict(r._mapping) for r in rows]


async def requeue(title: str, reason: str, current_attempts: int) -> None:
    """Re-insert a title with exponential backoff after a failure."""
    attempt = current_attempts + 1
    if attempt >= _MAX_ATTEMPTS:
        logger.warning("frontier_abandoned", title=title, attempts=attempt)
        return

    delay = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
    not_before = datetime.now(tz=UTC) + timedelta(seconds=delay)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                insert into wg_frontier (title, reason, enqueued_at, not_before, attempts)
                values (:title, :reason, now(), :not_before, :attempts)
                on conflict (title) do update
                    set attempts = excluded.attempts,
                        not_before = excluded.not_before
            """),
            {
                "title": title,
                "reason": reason,
                "not_before": not_before,
                "attempts": attempt,
            },
        )


async def frontier_size() -> int:
    """Return the number of items currently in the frontier."""
    engine = get_engine()
    async with engine.connect() as conn:
        return await conn.scalar(text("select count(*) from wg_frontier")) or 0


async def drain_frontier(
    batch_size: int = 20,
    poll_interval: float = 1.0,
    max_empty_polls: int = 3,
) -> list[dict]:
    """Collect all currently-queued frontier items, respecting not_before.

    Polls until the frontier has been empty for ``max_empty_polls`` consecutive
    checks (to catch items enqueued by concurrent workers during the crawl).
    Returns the full list of dequeued items.

    For the bootstrap we run this in a single-process loop; for the sync worker
    it's called as a continuous coroutine.
    """
    all_items: list[dict] = []
    empty_polls = 0

    while empty_polls < max_empty_polls:
        batch = await dequeue_batch(batch_size)
        if batch:
            all_items.extend(batch)
            empty_polls = 0
        else:
            empty_polls += 1
            if empty_polls < max_empty_polls:
                await asyncio.sleep(poll_interval)

    return all_items
