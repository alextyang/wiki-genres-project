"""Guard against weak wrong-direction display edges in the genre graph."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_ownership import BROAD_STYLE_TITLES

logger = structlog.get_logger(__name__)

DISPLAY_RELATIONS = {"subgenre", "derivative", "fusion_genre"}
RELATED_RELATION = "related_genre"
DIRECTION_GUARD_REASON = "direction_guard: weak display edge points to broader base genre"
MIN_BROADER_VIEW_RATIO = 2.0
MIN_BROADER_VIEW_DELTA = 100


@dataclass(frozen=True)
class DirectionEdge:
    from_genre_id: str
    to_genre_id: str
    from_title: str
    to_title: str
    relation: str
    source: str
    ordinal: int
    evidence_relation: str | None
    from_views: int | None
    to_views: int | None


@dataclass
class DirectionGuardStats:
    edges_scanned: int = 0
    cleared_existing: int = 0
    ignored: int = 0
    skipped_promoted_region_node: int = 0
    skipped_reviewed_schema: bool = False
    dry_run: bool = False
    sample: list[DirectionEdge] = field(default_factory=list)


def _normalize_title(title: str | None) -> str:
    return " ".join((title or "").casefold().replace("_", " ").split())


def _is_broad_title(title: str | None) -> bool:
    return _normalize_title(title) in BROAD_STYLE_TITLES


def _views_make_target_broader(edge: DirectionEdge) -> bool:
    from_views = edge.from_views or 0
    to_views = edge.to_views or 0
    if to_views <= from_views:
        return False
    return to_views >= from_views * MIN_BROADER_VIEW_RATIO and (
        to_views - from_views
    ) >= MIN_BROADER_VIEW_DELTA


def should_ignore_wrong_direction(edge: DirectionEdge) -> bool:
    """Return true for display edges where the target is clearly broader."""
    if edge.source == "manual_curation":
        return False
    if edge.relation not in DISPLAY_RELATIONS:
        return False
    if not _is_broad_title(edge.to_title):
        return False
    if _is_broad_title(edge.from_title):
        return False
    return _views_make_target_broader(edge)


async def guard_genre_direction(
    *,
    dry_run: bool = False,
    reset_existing: bool = True,
    sample_size: int = 25,
) -> DirectionGuardStats:
    await apply_migrations()
    stats = DirectionGuardStats(dry_run=dry_run)
    engine = get_engine()

    async with engine.begin() as conn:
        if reset_existing and not dry_run:
            result = await conn.execute(
                text("""
                    UPDATE wg_edges
                    SET is_ignored = false,
                        ignored_reason = NULL,
                        ignored_at = NULL
                    WHERE is_ignored = true
                      AND ignored_reason = :reason
                """),
                {"reason": DIRECTION_GUARD_REASON},
            )
            stats.cleared_existing = int(result.rowcount or 0)

        reviewed_schema_active = await conn.scalar(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM wg_genre_relationships
                    WHERE status = 'active'
                )
            """)
        )
        if reviewed_schema_active:
            stats.skipped_reviewed_schema = True
            logger.info(
                "genre_direction_guard_skipped",
                reason="reviewed_relationship_schema_active",
                cleared_existing=stats.cleared_existing,
                dry_run=dry_run,
            )
            return stats

        skipped = await conn.scalar(
            text("""
                SELECT count(*)
                FROM wg_edges e
                LEFT JOIN wg_region_promoted_genres from_region
                  ON from_region.genre_id = e.from_genre_id
                LEFT JOIN wg_region_promoted_genres to_region
                  ON to_region.genre_id = e.to_genre_id
                WHERE e.to_genre_id IS NOT NULL
                  AND e.relation = ANY(:relations)
                  AND (from_region.genre_id IS NOT NULL OR to_region.genre_id IS NOT NULL)
            """),
            {"relations": sorted(DISPLAY_RELATIONS)},
        )
        stats.skipped_promoted_region_node = int(skipped or 0)

        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            e.from_genre_id,
                            e.to_genre_id,
                            from_g.wikipedia_title AS from_title,
                            to_g.wikipedia_title AS to_title,
                            e.relation,
                            e.source,
                            e.ordinal,
                            e.evidence_relation,
                            from_g.monthly_views_p30 AS from_views,
                            to_g.monthly_views_p30 AS to_views
                        FROM wg_edges e
                        JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                        JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                        LEFT JOIN wg_region_promoted_genres from_region
                          ON from_region.genre_id = from_g.id
                        LEFT JOIN wg_region_promoted_genres to_region
                          ON to_region.genre_id = to_g.id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.relation = ANY(:relations)
                          AND e.is_ignored = false
                          AND e.source <> 'region_promotion'
                          AND from_g.deleted_at IS NULL
                          AND to_g.deleted_at IS NULL
                          AND from_g.is_non_genre = false
                          AND to_g.is_non_genre = false
                          AND from_region.genre_id IS NULL
                          AND to_region.genre_id IS NULL
                        ORDER BY from_g.wikipedia_title, to_g.wikipedia_title, e.source, e.ordinal
                    """),
                    {"relations": sorted(DISPLAY_RELATIONS)},
                )
            )
            .mappings()
            .fetchall()
        )
        stats.edges_scanned = len(rows)
        ignored: list[DirectionEdge] = []
        for row in rows:
            edge = DirectionEdge(
                from_genre_id=row["from_genre_id"],
                to_genre_id=row["to_genre_id"],
                from_title=row["from_title"],
                to_title=row["to_title"],
                relation=row["relation"],
                source=row["source"],
                ordinal=row["ordinal"],
                evidence_relation=row["evidence_relation"],
                from_views=row["from_views"],
                to_views=row["to_views"],
            )
            if not should_ignore_wrong_direction(edge):
                continue
            ignored.append(edge)
            if len(stats.sample) < sample_size:
                stats.sample.append(edge)

        stats.ignored = len(ignored)
        if dry_run:
            return stats

        for edge in ignored:
            await conn.execute(
                text("""
                    UPDATE wg_edges
                    SET is_ignored = true,
                        ignored_reason = :reason,
                        ignored_at = now()
                    WHERE from_genre_id = :from_id
                      AND relation = :relation
                      AND source = :source
                      AND ordinal = :ordinal
                """),
                {
                    "reason": DIRECTION_GUARD_REASON,
                    "from_id": edge.from_genre_id,
                    "relation": edge.relation,
                    "source": edge.source,
                    "ordinal": edge.ordinal,
                },
            )

    logger.info(
        "genre_direction_guard_complete",
        dry_run=dry_run,
        edges_scanned=stats.edges_scanned,
        ignored=stats.ignored,
    )
    return stats
