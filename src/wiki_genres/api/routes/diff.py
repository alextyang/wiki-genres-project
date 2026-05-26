"""Route: GET /v1/diff — incremental change feed since a timestamp."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import text

from wiki_genres.api.models import DiffGenreEntry, DiffResult
from wiki_genres.db import session_scope

router = APIRouter(tags=["diff"])


@router.get("/v1/diff", response_model=DiffResult)
async def diff(
    since: datetime = Query(
        ...,
        description="ISO 8601 timestamp. Return genres changed after this moment.",
    ),
) -> DiffResult:
    """Return genres whose content changed after *since*.

    ``last_changed_at`` is updated only when the raw wikitext SHA-256 changes,
    so this feed reflects genuine content edits — not every re-fetch.

    Intended use: consumers call ``/v1/diff?since={high_water_mark}`` on a
    schedule and merge the returned genres into their local mirror.
    """
    as_of = datetime.now(tz=UTC)

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text("""
                SELECT id, wikipedia_title, wikipedia_url, wikidata_qid, last_changed_at,
                       first_seen_at
                FROM wg_genres
                WHERE deleted_at IS NULL
                  AND is_non_genre = false
                  AND (
                    last_changed_at > :since
                    OR first_seen_at > :since
                  )
                ORDER BY last_changed_at DESC NULLS LAST, wikipedia_title
            """),
                    {"since": since},
                )
            )
            .mappings()
            .fetchall()
        )

    entries = [
        DiffGenreEntry(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikipedia_url=r["wikipedia_url"],
            wikidata_qid=r["wikidata_qid"],
            change_type=(
                "added" if r["first_seen_at"] and r["first_seen_at"] > since else "updated"
            ),
            last_changed_at=r["last_changed_at"],
        )
        for r in rows
    ]

    return DiffResult(
        since=since,
        as_of=as_of,
        genres_changed=entries,
        total=len(entries),
    )
