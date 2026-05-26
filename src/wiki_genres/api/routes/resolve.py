"""Routes: /v1/resolve and /v1/search."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from wiki_genres.api.models import (
    ResolveResult,
    SearchHit,
    SearchResults,
    TraversableSearchHit,
    TraversableSearchResults,
)
from wiki_genres.api.routes.genres import _build_genre_detail, _get_genre_row
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
        raise HTTPException(status_code=422, detail="Provide exactly one of: title, alias, qid.")

    async with session_scope() as session:
        row = matched_by = None

        if title:
            # 1. Exact title match.
            row = (
                (
                    await session.execute(
                        text("""
                    SELECT id
                    FROM wg_genres
                    WHERE wikipedia_title = :t
                      AND deleted_at IS NULL
                      AND is_non_genre = false
                """),
                        {"t": title},
                    )
                )
                .mappings()
                .fetchone()
            )
            if row:
                row = await _get_genre_row(session, row["id"])
                matched_by = "title"

            # 2. Redirect lookup.
            if row is None:
                redir = await session.scalar(
                    text("SELECT to_genre_id FROM wg_redirects WHERE from_title = :t"),
                    {"t": title},
                )
                if redir:
                    row = await _get_genre_row(session, redir)
                    if row:
                        matched_by = "redirect"

        elif alias:
            # Alias match (case-insensitive).
            genre_id = await session.scalar(
                text("""
                    SELECT a.genre_id
                    FROM wg_aliases a
                    JOIN wg_genres g ON g.id = a.genre_id
                    WHERE lower(a.alias) = lower(:a)
                      AND g.deleted_at IS NULL
                      AND g.is_non_genre = false
                    LIMIT 1
                """),
                {"a": alias},
            )
            if genre_id:
                row = await _get_genre_row(session, genre_id)
                matched_by = "alias"

        elif qid:
            row = (
                (
                    await session.execute(
                        text("""
                    SELECT id FROM wg_genres
                    WHERE wikidata_qid = :qid
                      AND deleted_at IS NULL
                      AND is_non_genre = false
                """),
                        {"qid": qid.upper()},
                    )
                )
                .mappings()
                .fetchone()
            )
            if row:
                row = await _get_genre_row(session, row["id"])
                matched_by = "qid"

        if row is None:
            lookup = title or alias or qid
            raise HTTPException(status_code=404, detail=f"No genre found for '{lookup}'.")
        resolved_input = title or alias or qid
        if matched_by is None or resolved_input is None:
            raise HTTPException(status_code=500, detail="Resolution state was incomplete.")

        genre = await _build_genre_detail(session, row)

    return ResolveResult(matched_by=matched_by, input=resolved_input, genre=genre)


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
        rows = (
            (
                await session.execute(
                    text("""
                SELECT
                    g.id,
                    g.wikipedia_title,
                    g.wikipedia_url,
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
                    g.deleted_at IS NULL
                    AND g.is_non_genre = false
                    AND (
                        to_tsvector('english',
                            coalesce(g.wikipedia_title, '') || ' ' ||
                            coalesce(g.summary, '')
                        ) @@ websearch_to_tsquery('english', :q)
                        OR g.wikipedia_title ILIKE :ilike
                        OR EXISTS (
                            SELECT 1 FROM wg_aliases a
                            WHERE a.genre_id = g.id AND a.alias ILIKE :ilike
                        )
                    )
                ORDER BY rank DESC, g.wikipedia_title
                LIMIT :limit
            """),
                    {"q": q, "ilike": f"%{q}%", "limit": limit},
                )
            )
            .mappings()
            .fetchall()
        )

    hits = [
        SearchHit(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikipedia_url=r["wikipedia_url"],
            wikidata_qid=r["wikidata_qid"],
            has_infobox=r["has_infobox"],
            summary=r["summary"],
            rank=float(r["rank"]),
        )
        for r in rows
    ]
    return SearchResults(query=q, hits=hits, total=len(hits))


@router.get("/v1/search/traversable/random", response_model=TraversableSearchHit)
async def random_traversable() -> TraversableSearchHit:
    """Return one random genre that has an indexed path from the Music root."""
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text("""
                WITH candidate AS (
                    SELECT genre_id
                    FROM (
                        SELECT DISTINCT r.genre_id
                        FROM wg_music_reachable_parents r
                        JOIN wg_genres g ON g.id = r.genre_id
                        WHERE g.deleted_at IS NULL
                          AND g.is_non_genre = false
                          AND r.genre_id <> r.root_genre_id
                    ) traversable
                    ORDER BY random()
                    LIMIT 1
                )
                SELECT
                    g.id,
                    g.wikipedia_title,
                    g.wikipedia_url,
                    g.wikidata_qid,
                    g.has_infobox,
                    g.summary,
                    g.monthly_views_p30,
                    best.depth_from_music,
                    best.path_genre_ids,
                    (
                        SELECT array_agg(path_g.wikipedia_title ORDER BY path_item.ordinality)
                        FROM unnest(best.path_genre_ids)
                            WITH ORDINALITY AS path_item(genre_id, ordinality)
                        JOIN wg_genres path_g ON path_g.id = path_item.genre_id
                    ) AS path_titles
                FROM candidate c
                JOIN wg_genres g ON g.id = c.genre_id
                JOIN LATERAL (
                    SELECT r.depth_from_music, r.parent_depth_from_music, r.path_genre_ids
                    FROM wg_music_reachable_parents r
                    WHERE r.genre_id = g.id
                    ORDER BY
                        r.depth_from_music,
                        r.parent_depth_from_music,
                        r.parent_relation,
                        r.parent_source,
                        r.parent_ordinal
                    LIMIT 1
                ) best ON true
            """)
                )
            )
            .mappings()
            .fetchone()
        )

    if row is None:
        raise HTTPException(status_code=404, detail="No traversable genres are indexed.")

    return TraversableSearchHit(
        id=row["id"],
        wikipedia_title=row["wikipedia_title"],
        wikipedia_url=row["wikipedia_url"],
        wikidata_qid=row["wikidata_qid"],
        has_infobox=row["has_infobox"],
        summary=row["summary"],
        rank=0.0,
        monthly_views_p30=row["monthly_views_p30"],
        depth_from_music=row["depth_from_music"],
        path_genre_ids=row["path_genre_ids"],
        path_titles=row["path_titles"] or [],
    )


@router.get("/v1/search/traversable", response_model=TraversableSearchResults)
async def search_traversable(
    q: str = Query(..., min_length=1, description="Search query."),
    limit: int = Query(12, ge=1, le=50),
) -> TraversableSearchResults:
    """Search only genres that have an indexed path from the Music root."""
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text("""
                WITH matched AS (
                    SELECT
                        g.id,
                        g.wikipedia_title,
                        g.wikipedia_url,
                        g.wikidata_qid,
                        g.has_infobox,
                        g.summary,
                        g.monthly_views_p30,
                        ts_rank(
                            to_tsvector('english',
                                coalesce(g.wikipedia_title, '') || ' ' ||
                                coalesce(g.summary, '')
                            ),
                            websearch_to_tsquery('english', :q)
                        ) AS rank
                    FROM wg_genres g
                    WHERE
                        g.deleted_at IS NULL
                        AND g.is_non_genre = false
                        AND (
                            to_tsvector('english',
                                coalesce(g.wikipedia_title, '') || ' ' ||
                                coalesce(g.summary, '')
                            ) @@ websearch_to_tsquery('english', :q)
                            OR g.wikipedia_title ILIKE :ilike
                            OR EXISTS (
                                SELECT 1 FROM wg_aliases a
                                WHERE a.genre_id = g.id AND a.alias ILIKE :ilike
                            )
                        )
                )
                SELECT
                    m.id,
                    m.wikipedia_title,
                    m.wikipedia_url,
                    m.wikidata_qid,
                    m.has_infobox,
                    m.summary,
                    m.monthly_views_p30,
                    m.rank,
                    best.depth_from_music,
                    best.path_genre_ids,
                    (
                        SELECT array_agg(path_g.wikipedia_title ORDER BY path_item.ordinality)
                        FROM unnest(best.path_genre_ids)
                            WITH ORDINALITY AS path_item(genre_id, ordinality)
                        JOIN wg_genres path_g ON path_g.id = path_item.genre_id
                    ) AS path_titles
                FROM matched m
                JOIN LATERAL (
                    SELECT r.depth_from_music, r.parent_depth_from_music, r.path_genre_ids
                    FROM wg_music_reachable_parents r
                    WHERE r.genre_id = m.id
                    ORDER BY
                        r.depth_from_music,
                        r.parent_depth_from_music,
                        r.parent_relation,
                        r.parent_source,
                        r.parent_ordinal
                    LIMIT 1
                ) best ON true
                ORDER BY
                    m.rank DESC,
                    m.monthly_views_p30 DESC NULLS LAST,
                    best.depth_from_music,
                    m.wikipedia_title
                LIMIT :limit
            """),
                    {"q": q, "ilike": f"%{q}%", "limit": limit},
                )
            )
            .mappings()
            .fetchall()
        )

    hits = [
        TraversableSearchHit(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikipedia_url=r["wikipedia_url"],
            wikidata_qid=r["wikidata_qid"],
            has_infobox=r["has_infobox"],
            summary=r["summary"],
            monthly_views_p30=r["monthly_views_p30"],
            rank=float(r["rank"]),
            depth_from_music=r["depth_from_music"],
            path_genre_ids=r["path_genre_ids"],
            path_titles=r["path_titles"] or [],
        )
        for r in rows
    ]
    return TraversableSearchResults(query=q, hits=hits, total=len(hits))
