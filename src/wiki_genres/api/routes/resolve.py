"""Routes: /v1/resolve and /v1/search."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from wiki_genres.api.models import ResolveResult, SearchHit, SearchResults
from wiki_genres.api.routes.genres import _build_genre_detail
from wiki_genres.db import session_scope

router = APIRouter(tags=["resolve"])


# ------------------------------------------------------------------ #
# GET /v1/resolve                                                     #
# ------------------------------------------------------------------ #

@router.get("/v1/resolve", response_model=ResolveResult)
async def resolve(
    title: str | None = Query(None, description="Wikipedia page title (exact)."),
    alias: str | None = Query(None, description="Alias / alternate name (case-insensitive)."),
    qid: str | None = Query(None, description="Wikidata QID, e.g. Q188450."),
) -> ResolveResult:
    """Resolve an alias, title, or Wikidata QID to a canonical genre record.

    Exactly one of `title`, `alias`, or `qid` must be provided.
    Resolution order for `title`: exact match → redirect lookup.
    """
    if sum(x is not None for x in (title, alias, qid)) != 1:
        raise HTTPException(
            status_code=422, detail="Provide exactly one of: title, alias, qid."
        )

    async with session_scope() as session:
        row = matched_by = None

        if title:
            # 1. Exact title match.
            row = (await session.execute(
                text("SELECT * FROM wg_genres WHERE wikipedia_title = :t"),
                {"t": title},
            )).mappings().fetchone()
            if row:
                matched_by = "title"

            # 2. Redirect lookup.
            if row is None:
                redir = await session.scalar(
                    text("SELECT to_genre_id FROM wg_redirects WHERE from_title = :t"),
                    {"t": title},
                )
                if redir:
                    row = (await session.execute(
                        text("SELECT * FROM wg_genres WHERE id = :id"),
                        {"id": redir},
                    )).mappings().fetchone()
                    if row:
                        matched_by = "redirect"

        elif alias:
            # Alias match (case-insensitive).
            genre_id = await session.scalar(
                text("SELECT genre_id FROM wg_aliases WHERE lower(alias) = lower(:a) LIMIT 1"),
                {"a": alias},
            )
            if genre_id:
                row = (await session.execute(
                    text("SELECT * FROM wg_genres WHERE id = :id"),
                    {"id": genre_id},
                )).mappings().fetchone()
                matched_by = "alias"

        elif qid:
            row = (await session.execute(
                text("SELECT * FROM wg_genres WHERE wikidata_qid = :qid"),
                {"qid": qid.upper()},
            )).mappings().fetchone()
            matched_by = "qid"

        if row is None:
            lookup = title or alias or qid
            raise HTTPException(status_code=404, detail=f"No genre found for '{lookup}'.")

        genre = await _build_genre_detail(session, row)

    return ResolveResult(matched_by=matched_by, input=(title or alias or qid), genre=genre)


# ------------------------------------------------------------------ #
# GET /v1/search                                                      #
# ------------------------------------------------------------------ #

@router.get("/v1/search", response_model=SearchResults)
async def search(
    q: str = Query(..., min_length=1, description="Search query."),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResults:
    """Full-text search over genre titles, aliases, and summaries.

    Uses PostgreSQL ``websearch_to_tsquery`` syntax (e.g. ``"hip hop" OR techno``).
    Falls back to a simple ILIKE on title if no full-text matches are found.
    """
    async with session_scope() as session:
        rows = (await session.execute(
            text("""
                SELECT
                    g.id,
                    g.wikipedia_title,
                    g.wikidata_qid,
                    g.has_infobox,
                    g.summary,
                    ts_rank(
                        to_tsvector('english',
                            coalesce(g.wikipedia_title, '')  || ' ' ||
                            coalesce(g.summary, '')
                        ),
                        websearch_to_tsquery('english', :q)
                    ) AS rank
                FROM wg_genres g
                WHERE
                    to_tsvector('english',
                        coalesce(g.wikipedia_title, '') || ' ' ||
                        coalesce(g.summary, '')
                    ) @@ websearch_to_tsquery('english', :q)
                    OR g.wikipedia_title ILIKE :ilike
                    OR EXISTS (
                        SELECT 1 FROM wg_aliases a
                        WHERE a.genre_id = g.id AND a.alias ILIKE :ilike
                    )
                ORDER BY rank DESC, g.wikipedia_title
                LIMIT :limit
            """),
            {"q": q, "ilike": f"%{q}%", "limit": limit},
        )).mappings().fetchall()

    hits = [
        SearchHit(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikidata_qid=r["wikidata_qid"],
            has_infobox=r["has_infobox"],
            summary=r["summary"],
            rank=float(r["rank"]),
        )
        for r in rows
    ]
    return SearchResults(query=q, hits=hits, total=len(hits))
