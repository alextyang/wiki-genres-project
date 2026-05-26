"""Database curation routines for approved public genre rows."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.curation import (
    MANUAL_CURATION_EDGE_SOURCE,
    MANUAL_DISPLAY_EDGES,
    MANUAL_MUSIC_GENRE_TITLES,
    MANUAL_NON_GENRE_TITLES,
    MUSIC_CATEGORY_MARKERS,
)
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)


@dataclass
class CurationStats:
    total_rows: int = 0
    approved_rows: int = 0
    non_genre_rows: int = 0
    changed_rows: int = 0
    forced_non_genre_rows: int = 0
    manual_edges_upserted: int = 0
    manual_edges_missing_titles: list[str] = field(default_factory=list)


async def apply_genre_curation(
    *,
    force_non_genre_titles: list[str] | None = None,
) -> CurationStats:
    """Recompute ``wg_genres.is_non_genre`` from strict approval rules.

    The approval filter mirrors the bootstrap classifier:
    - music-genre infobox pages;
    - Wikidata ``instance_of`` / ``subclass_of`` music genre or musical style;
    - Wikipedia categories that explicitly say music genre/style;
    - manually reviewed titles from ``wiki_genres.curation``.

    ``force_non_genre_titles`` is a final override for source pages that were
    temporarily crawled but proved to contain no approved genre links.
    """
    await apply_migrations()
    force_non_genre_titles = sorted(
        set(force_non_genre_titles or []) | set(MANUAL_NON_GENRE_TITLES)
    )
    stats = CurationStats()
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TEMPORARY TABLE wg_manual_approved_titles (
                    wikipedia_title text PRIMARY KEY
                ) ON COMMIT DROP
            """)
        )
        if MANUAL_MUSIC_GENRE_TITLES:
            await conn.execute(
                text("""
                    INSERT INTO wg_manual_approved_titles (wikipedia_title)
                    SELECT DISTINCT unnest(CAST(:titles AS text[]))
                """),
                {"titles": sorted(MANUAL_MUSIC_GENRE_TITLES)},
            )

        await conn.execute(
            text("""
                CREATE TEMPORARY TABLE wg_force_non_genre_titles (
                    wikipedia_title text PRIMARY KEY
                ) ON COMMIT DROP
            """)
        )
        if force_non_genre_titles:
            await conn.execute(
                text("""
                    INSERT INTO wg_force_non_genre_titles (wikipedia_title)
                    SELECT DISTINCT unnest(CAST(:titles AS text[]))
                """),
                {"titles": sorted(force_non_genre_titles)},
            )

        await conn.execute(
            text("""
                CREATE TEMPORARY TABLE wg_approved_genre_ids ON COMMIT DROP AS
                SELECT g.id
                FROM wg_genres g
                WHERE (
                    g.has_infobox
                    OR EXISTS (
                        SELECT 1
                        FROM wg_edges e
                        WHERE e.from_genre_id = g.id
                          AND e.source = 'wikidata'
                          AND e.relation IN ('instance_of', 'subclass_of')
                          AND e.to_raw_label IN ('Q188451', 'Q2944929')
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM wg_categories c
                        WHERE c.genre_id = g.id
                          AND c.category ILIKE ANY(:markers)
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM wg_manual_approved_titles t
                        WHERE t.wikipedia_title = g.wikipedia_title
                    )
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM wg_force_non_genre_titles f
                    WHERE f.wikipedia_title = g.wikipedia_title
                )
            """),
            {"markers": [f"%{marker}%" for marker in MUSIC_CATEGORY_MARKERS]},
        )

        result = await conn.execute(
            text("""
                WITH next_state AS (
                    SELECT
                        g.id,
                        NOT EXISTS (
                            SELECT 1 FROM wg_approved_genre_ids a WHERE a.id = g.id
                        ) AS next_is_non_genre
                    FROM wg_genres g
                    WHERE g.deleted_at IS NULL
                ),
                updated AS (
                    UPDATE wg_genres g
                    SET
                        is_non_genre = n.next_is_non_genre,
                        non_genre_reviewed_at = CASE
                            WHEN n.next_is_non_genre = false THEN NULL
                            WHEN g.is_non_genre = true
                             AND g.non_genre_reviewed_at IS NOT NULL
                            THEN g.non_genre_reviewed_at
                            ELSE now()
                        END,
                        non_genre_review_note = CASE
                            WHEN n.next_is_non_genre = false THEN NULL
                            WHEN EXISTS (
                                SELECT 1
                                FROM wg_force_non_genre_titles f
                                WHERE f.wikipedia_title = g.wikipedia_title
                            )
                            THEN 'source-page crawl found no approved genre links'
                            ELSE 'manual review: not an approved music genre/style entry'
                        END
                    FROM next_state n
                    WHERE g.id = n.id
                      AND g.is_non_genre IS DISTINCT FROM n.next_is_non_genre
                    RETURNING g.id
                )
                SELECT count(*) FROM updated
            """)
        )
        stats.changed_rows = int(result.scalar_one())

        counts = (
            (
                await conn.execute(
                    text("""
                SELECT
                    count(*) FILTER (WHERE deleted_at IS NULL) AS total_rows,
                    count(*) FILTER (
                        WHERE deleted_at IS NULL AND is_non_genre = false
                    ) AS approved_rows,
                    count(*) FILTER (
                        WHERE deleted_at IS NULL AND is_non_genre = true
                    ) AS non_genre_rows,
                    count(*) FILTER (
                        WHERE deleted_at IS NULL
                          AND wikipedia_title IN (
                              SELECT wikipedia_title FROM wg_force_non_genre_titles
                          )
                          AND is_non_genre = true
                    ) AS forced_non_genre_rows
                FROM wg_genres
            """)
                )
            )
            .mappings()
            .one()
        )
        stats.total_rows = counts["total_rows"]
        stats.approved_rows = counts["approved_rows"]
        stats.non_genre_rows = counts["non_genre_rows"]
        stats.forced_non_genre_rows = counts["forced_non_genre_rows"]

        await conn.execute(
            text("DELETE FROM wg_edges WHERE source = :source"),
            {"source": MANUAL_CURATION_EDGE_SOURCE},
        )
        if MANUAL_DISPLAY_EDGES:
            await conn.execute(
                text("""
                    CREATE TEMPORARY TABLE wg_manual_display_edges (
                        parent_title text NOT NULL,
                        child_title text NOT NULL,
                        relation text NOT NULL,
                        ordinal integer NOT NULL
                    ) ON COMMIT DROP
                """)
            )
            await conn.execute(
                text("""
                    INSERT INTO wg_manual_display_edges (
                        parent_title, child_title, relation, ordinal
                    )
                    VALUES (:parent_title, :child_title, :relation, :ordinal)
                """),
                [
                    {
                        "parent_title": edge.parent_title,
                        "child_title": edge.child_title,
                        "relation": edge.relation,
                        "ordinal": ordinal,
                    }
                    for ordinal, edge in enumerate(MANUAL_DISPLAY_EDGES)
                ],
            )

            missing_rows = (
                (
                    await conn.execute(
                        text("""
                    SELECT title
                    FROM (
                        SELECT parent_title AS title FROM wg_manual_display_edges
                        UNION
                        SELECT child_title AS title FROM wg_manual_display_edges
                    ) titles
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM wg_genres g
                        WHERE g.wikipedia_title = titles.title
                          AND g.deleted_at IS NULL
                          AND g.is_non_genre = false
                    )
                    ORDER BY title
                """)
                    )
                )
                .mappings()
                .fetchall()
            )
            stats.manual_edges_missing_titles = [row["title"] for row in missing_rows]

            result = await conn.execute(
                text("""
                    INSERT INTO wg_edges (
                        from_genre_id,
                        to_genre_id,
                        to_raw_label,
                        relation,
                        source,
                        ordinal,
                        first_seen_at
                    )
                    SELECT
                        parent_g.id,
                        child_g.id,
                        child_g.wikipedia_title,
                        m.relation,
                        :source,
                        m.ordinal,
                        now()
                    FROM wg_manual_display_edges m
                    JOIN wg_genres parent_g
                      ON parent_g.wikipedia_title = m.parent_title
                     AND parent_g.deleted_at IS NULL
                     AND parent_g.is_non_genre = false
                    JOIN wg_genres child_g
                      ON child_g.wikipedia_title = m.child_title
                     AND child_g.deleted_at IS NULL
                     AND child_g.is_non_genre = false
                """),
                {"source": MANUAL_CURATION_EDGE_SOURCE},
            )
            stats.manual_edges_upserted = int(result.rowcount or 0)

        await conn.execute(
            text("""
                INSERT INTO wg_snapshots (
                    id, kind, started_at, finished_at, nodes_total, edges_total, notes
                )
                SELECT
                    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                        || '-curation-filter',
                    'reconciler',
                    now(),
                    now(),
                    :nodes,
                    (
                        SELECT count(*)
                        FROM wg_edges e
                        JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                        LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                        WHERE from_g.is_non_genre = false
                          AND from_g.deleted_at IS NULL
                          AND (
                            e.to_genre_id IS NULL
                            OR (to_g.is_non_genre = false AND to_g.deleted_at IS NULL)
                          )
                    ),
                    :notes
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "nodes": stats.approved_rows,
                "notes": (
                    "Adjusted genre curation filter. "
                    f"changed={stats.changed_rows} "
                    f"forced_non_genre={stats.forced_non_genre_rows} "
                    f"manual_edges={stats.manual_edges_upserted}"
                ),
            },
        )

    logger.info(
        "genre_curation_complete",
        total_rows=stats.total_rows,
        approved_rows=stats.approved_rows,
        non_genre_rows=stats.non_genre_rows,
        changed_rows=stats.changed_rows,
        forced_non_genre_rows=stats.forced_non_genre_rows,
        manual_edges_upserted=stats.manual_edges_upserted,
        manual_edges_missing_titles=stats.manual_edges_missing_titles,
    )
    return stats
