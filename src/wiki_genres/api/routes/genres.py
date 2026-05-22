"""Routes: /v1/genres and /v1/genres/{id}/..."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from wiki_genres.api.models import (
    AliasOut,
    EdgeOut,
    GenreDetail,
    GenreListItem,
    NeighborOut,
    OriginOut,
    PageviewEntry,
    PaginatedGenres,
)
from wiki_genres.db import session_scope

router = APIRouter(prefix="/v1/genres", tags=["genres"])


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

async def _get_genre_row(session, genre_id: str, include_deleted: bool = False):
    """Fetch the core wg_genres row by ID."""
    deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
    row = await session.execute(
        text(f"SELECT * FROM wg_genres WHERE id = :id {deleted_filter}"),
        {"id": genre_id},
    )
    return row.mappings().fetchone()


async def _build_genre_detail(session, row) -> GenreDetail:
    """Assemble a GenreDetail from a wg_genres row plus related tables."""
    gid = row["id"]

    edges_out = (await session.execute(
        text("""
            SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                   e.relation, e.source, e.ordinal
            FROM wg_edges e
            WHERE e.from_genre_id = :gid
            ORDER BY e.relation, e.source, e.ordinal
        """),
        {"gid": gid},
    )).mappings().fetchall()

    edges_in = (await session.execute(
        text("""
            SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                   e.relation, e.source, e.ordinal
            FROM wg_edges e
            WHERE e.to_genre_id = :gid
            ORDER BY e.relation, e.source, e.ordinal
        """),
        {"gid": gid},
    )).mappings().fetchall()

    aliases = (await session.execute(
        text("SELECT alias, source FROM wg_aliases WHERE genre_id = :gid ORDER BY alias"),
        {"gid": gid},
    )).mappings().fetchall()

    origins = (await session.execute(
        text("""
            SELECT kind, value, parsed_year_start, parsed_year_end, parsed_region
            FROM wg_origins WHERE genre_id = :gid
        """),
        {"gid": gid},
    )).mappings().fetchall()

    instruments = (await session.execute(
        text("SELECT instrument FROM wg_instruments WHERE genre_id = :gid ORDER BY instrument"),
        {"gid": gid},
    )).mappings().fetchall()

    categories = (await session.execute(
        text("SELECT category FROM wg_categories WHERE genre_id = :gid ORDER BY category"),
        {"gid": gid},
    )).mappings().fetchall()

    return GenreDetail(
        id=row["id"],
        wikidata_qid=row["wikidata_qid"],
        wikipedia_title=row["wikipedia_title"],
        wikipedia_url=row["wikipedia_url"],
        has_infobox=row["has_infobox"],
        infobox_color=row["infobox_color"],
        summary=row["summary"],
        last_changed_at=row["last_changed_at"],
        last_fetched_at=row["last_fetched_at"],
        outbound_edges=[EdgeOut(**dict(e)) for e in edges_out],
        inbound_edges=[EdgeOut(**dict(e)) for e in edges_in],
        aliases=[AliasOut(**dict(a)) for a in aliases],
        origins=[OriginOut(**dict(o)) for o in origins],
        instruments=[r["instrument"] for r in instruments],
        categories=[r["category"] for r in categories],
    )


# ------------------------------------------------------------------ #
# GET /v1/genres                                                      #
# ------------------------------------------------------------------ #

@router.get("", response_model=PaginatedGenres)
async def list_genres(
    q: str | None = Query(None, description="Filter by title substring (case-insensitive)."),
    has_infobox: bool | None = Query(None),
    updated_since: str | None = Query(None, description="ISO 8601 timestamp."),
    include_deleted: bool = Query(False, description="Include soft-deleted genres."),
    sort_by: str = Query("title", pattern="^(title|views)$", description="Sort by title or monthly views."),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> PaginatedGenres:
    """Paginated list of genres with optional filters."""
    offset = (page - 1) * size
    conditions: list[str] = []
    params: dict = {"limit": size, "offset": offset}

    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if q:
        conditions.append("wikipedia_title ILIKE :q")
        params["q"] = f"%{q}%"
    if has_infobox is not None:
        conditions.append("has_infobox = :has_infobox")
        params["has_infobox"] = has_infobox
    if updated_since:
        conditions.append("last_changed_at >= :since")
        params["since"] = updated_since

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = (
        "ORDER BY monthly_views_p30 DESC NULLS LAST, wikipedia_title"
        if sort_by == "views"
        else "ORDER BY wikipedia_title"
    )

    async with session_scope() as session:
        total = (await session.scalar(
            text(f"SELECT count(*) FROM wg_genres {where}"),
            params,
        )) or 0

        rows = (await session.execute(
            text(f"""
                SELECT id, wikidata_qid, wikipedia_title, wikipedia_url,
                       has_infobox, infobox_color, summary,
                       last_changed_at, last_fetched_at, monthly_views_p30
                FROM wg_genres {where}
                {order}
                LIMIT :limit OFFSET :offset
            """),
            params,
        )).mappings().fetchall()

    return PaginatedGenres(
        items=[GenreListItem(**dict(r)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
    )


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}                                                 #
# ------------------------------------------------------------------ #

@router.get("/{genre_id}", response_model=GenreDetail)
async def get_genre(genre_id: str) -> GenreDetail:
    """Full genre detail: edges (in + out), aliases, origins, instruments."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")
        return await _build_genre_detail(session, row)


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/edges                                           #
# ------------------------------------------------------------------ #

@router.get("/{genre_id}/edges", response_model=list[EdgeOut])
async def get_genre_edges(
    genre_id: str,
    relation: str | None = Query(None, description="Filter by relation type."),
    direction: str = Query("out", pattern="^(out|in|both)$"),
) -> list[EdgeOut]:
    """Filtered edge list for a genre."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rel_filter = "AND e.relation = :relation" if relation else ""
        params = {"gid": genre_id}
        if relation:
            params["relation"] = relation

        results: list[EdgeOut] = []

        if direction in ("out", "both"):
            rows = (await session.execute(
                text(f"""
                    SELECT from_genre_id, to_genre_id, to_raw_label, relation, source, ordinal
                    FROM wg_edges e WHERE e.from_genre_id = :gid {rel_filter}
                    ORDER BY relation, source, ordinal
                """),
                params,
            )).mappings().fetchall()
            results.extend(EdgeOut(**dict(r)) for r in rows)

        if direction in ("in", "both"):
            rows = (await session.execute(
                text(f"""
                    SELECT from_genre_id, to_genre_id, to_raw_label, relation, source, ordinal
                    FROM wg_edges e WHERE e.to_genre_id = :gid {rel_filter}
                    ORDER BY relation, source, ordinal
                """),
                params,
            )).mappings().fetchall()
            results.extend(EdgeOut(**dict(r)) for r in rows)

    return results


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/neighbors                                       #
# ------------------------------------------------------------------ #

@router.get("/{genre_id}/neighbors", response_model=list[NeighborOut])
async def get_genre_neighbors(
    genre_id: str,
    depth: int = Query(1, ge=1, le=3, description="BFS depth (max 3)."),
    relation: str | None = Query(None, description="Restrict to one relation type."),
) -> list[NeighborOut]:
    """BFS expansion up to *depth* hops. Useful for graph visualisations."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rel_filter = "AND e.relation = :relation" if relation else ""
        params: dict = {"start": genre_id, "max_depth": depth - 1}
        if relation:
            params["relation"] = relation

        # Recursive CTE with cycle guard via `visited` array.
        rows = (await session.execute(
            text(f"""
                WITH RECURSIVE bfs AS (
                    SELECT
                        e.to_genre_id       AS genre_id,
                        e.relation,
                        e.source,
                        0                   AS depth,
                        ARRAY[e.from_genre_id, e.to_genre_id] AS visited
                    FROM wg_edges e
                    WHERE e.from_genre_id = :start
                      AND e.to_genre_id IS NOT NULL
                      {rel_filter}

                    UNION ALL

                    SELECT
                        e.to_genre_id,
                        e.relation,
                        e.source,
                        bfs.depth + 1,
                        bfs.visited || e.to_genre_id
                    FROM wg_edges e
                    JOIN bfs ON bfs.genre_id = e.from_genre_id
                    WHERE e.to_genre_id IS NOT NULL
                      AND NOT (e.to_genre_id = ANY(bfs.visited))
                      AND bfs.depth < :max_depth
                      {rel_filter}
                )
                SELECT DISTINCT ON (bfs.genre_id)
                    g.id, g.wikipedia_title, g.wikidata_qid,
                    g.has_infobox, g.infobox_color,
                    bfs.relation, bfs.source,
                    bfs.depth
                FROM bfs
                JOIN wg_genres g ON g.id = bfs.genre_id
                ORDER BY bfs.genre_id, bfs.depth
            """),
            params,
        )).mappings().fetchall()

    return [
        NeighborOut(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikidata_qid=r["wikidata_qid"],
            has_infobox=r["has_infobox"],
            infobox_color=r["infobox_color"],
            relation=r["relation"],
            source=r["source"],
            depth=r["depth"] + 1,  # 1-indexed for callers
        )
        for r in rows
    ]


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/pageviews                                       #
# ------------------------------------------------------------------ #

@router.get("/{genre_id}/pageviews", response_model=list[PageviewEntry])
async def get_genre_pageviews(genre_id: str) -> list[PageviewEntry]:
    """Monthly pageview history for a genre (most recent first)."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rows = (await session.execute(
            text("""
                SELECT year, month, views
                FROM wg_pageviews
                WHERE genre_id = :gid
                ORDER BY year DESC, month DESC
            """),
            {"gid": genre_id},
        )).mappings().fetchall()

    return [PageviewEntry(**dict(r)) for r in rows]
