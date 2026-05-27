"""Derived pure-region graph projection from the genre node graph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_graph import (
    clean_region_name,
    infer_region_kind,
    normalize_region_id,
)

logger = structlog.get_logger(__name__)

REGION_NODE_MAPPING_TYPES = {
    "region_music_page",
    "region_promoted_genre",
    "title_music_of",
    "title_music_in",
    "category_music_of",
    "category_music_in",
    "category_region_music",
}

REGION_EDGE_RELATIONS = {
    "part_of",
    "subclass_of",
    "instance_of",
    "regional_scene",
    "local_scene",
    "broader_genres",
    "subgenres",
    "regional_variations",
    "subgenre",
    "derivative",
    "fusion_genre",
}

INVERTED_REGION_EDGE_RELATIONS = {
    "regional_scene",
    "local_scene",
}

NON_REGION_TITLE_REGIONS = {
    "advertising",
    "movement against apartheid",
    "pornography",
    "round",
}


@dataclass(frozen=True)
class RegionNodeMappingCandidate:
    genre_id: str
    region_name: str
    mapping_type: str
    confidence: float


@dataclass
class PureRegionGraphStats:
    mappings_upserted: int = 0
    relationships_upserted: int = 0
    regions_upserted: int = 0
    skipped_title_mappings: int = 0
    reset: bool = False
    sample: list[str] = field(default_factory=list)


def region_mapping_from_title(title: str, genre_id: str) -> RegionNodeMappingCandidate | None:
    """Infer a region-node mapping from music-region page/category titles."""
    clean = " ".join(str(title or "").replace("_", " ").split())
    if not clean:
        return None

    category = False
    match = re.match(r"^category:\s*(.+)$", clean, flags=re.IGNORECASE)
    if match:
        category = True
        clean = match.group(1).strip()

    patterns: tuple[tuple[str, str, float], ...] = (
        (r"^music of (?:the )?(.+)$", "category_music_of" if category else "title_music_of", 0.84),
        (r"^music in (?:the )?(.+)$", "category_music_in" if category else "title_music_in", 0.78),
    )
    for pattern, mapping_type, confidence in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            region_name = clean_region_name(match.group(1))
            if region_name and is_plausible_title_region(region_name):
                return RegionNodeMappingCandidate(
                    genre_id=genre_id,
                    region_name=region_name,
                    mapping_type=mapping_type,
                    confidence=confidence,
                )

    if category:
        match = re.match(r"^(.+?) music$", clean, flags=re.IGNORECASE)
        if match:
            region_name = clean_region_name(match.group(1))
            if region_name and is_plausible_title_region(region_name):
                return RegionNodeMappingCandidate(
                    genre_id=genre_id,
                    region_name=region_name,
                    mapping_type="category_region_music",
                    confidence=0.62,
                )

    return None


def is_plausible_title_region(region_name: str) -> bool:
    return region_name.strip().lower() not in NON_REGION_TITLE_REGIONS


def pure_region_relation_for_edge(
    *,
    source_edge_relation: str,
    from_region_kind: str | None,
    source_direction: str,
) -> str:
    """Normalize a genre edge between region nodes into a pure region relation."""
    kind = from_region_kind or "unknown"
    if kind == "historical_region":
        return "historical_region_of"
    if kind == "diaspora_region":
        return "diaspora_region_of"
    if kind == "language_region":
        return "language_region_of"
    if kind == "cultural_region":
        return "cultural_region_of"
    if kind in {"city", "subregion", "territory"}:
        return "admin_parent"
    if source_edge_relation == "local_scene":
        return "admin_parent"
    if source_edge_relation == "regional_scene" and source_direction == "inverted":
        return "cultural_region_of"
    return "part_of"


def _add_sample(stats: PureRegionGraphStats, item: str, sample_size: int) -> None:
    if sample_size > 0 and len(stats.sample) < sample_size:
        stats.sample.append(item)


async def rebuild_pure_region_graph(*, sample_size: int = 25) -> PureRegionGraphStats:
    """Rebuild derived region-node mappings and pure region relationships."""
    await apply_migrations()
    stats = PureRegionGraphStats(reset=True)
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM wg_pure_region_relationships"))
        await conn.execute(text("DELETE FROM wg_region_node_mappings"))
        await _delete_orphaned_projection_regions(conn)

        await _insert_existing_region_node_mappings(conn, stats)
        await _insert_title_region_node_mappings(conn, stats, sample_size=sample_size)
        await _insert_pure_region_relationships(conn, stats, sample_size=sample_size)

    logger.info(
        "pure_region_graph_rebuilt",
        mappings_upserted=stats.mappings_upserted,
        regions_upserted=stats.regions_upserted,
        relationships_upserted=stats.relationships_upserted,
    )
    return stats


async def _delete_orphaned_projection_regions(conn: Any) -> None:
    await conn.execute(
        text("""
            DELETE FROM wg_regions r
            WHERE r.raw_payload ->> 'source' = 'pure_region_graph'
              AND NOT EXISTS (
                  SELECT 1 FROM wg_region_music_pages page WHERE page.region_id = r.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM wg_region_promoted_genres promoted WHERE promoted.region_id = r.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM wg_region_relationships rel
                  WHERE rel.from_region_id = r.id OR rel.to_region_id = r.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM wg_region_genre_relationships rel WHERE rel.region_id = r.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM wg_region_inferred_genres inferred WHERE inferred.region_id = r.id
              )
        """)
    )


async def _insert_existing_region_node_mappings(conn: Any, stats: PureRegionGraphStats) -> None:
    result = await conn.execute(
        text("""
            INSERT INTO wg_region_node_mappings (
                genre_id,
                region_id,
                mapping_type,
                source_title,
                source_is_non_genre,
                confidence,
                raw_payload,
                updated_at
            )
            SELECT DISTINCT ON (page.genre_id, page.region_id)
                page.genre_id,
                page.region_id,
                'region_music_page',
                genre.wikipedia_title,
                genre.is_non_genre,
                greatest(page.confidence, 0.86),
                jsonb_build_object(
                    'source', 'wg_region_music_pages',
                    'role', page.role,
                    'source_type', page.source_type
                ),
                now()
            FROM wg_region_music_pages page
            JOIN wg_genres genre ON genre.id = page.genre_id
            JOIN wg_regions region ON region.id = page.region_id
            WHERE genre.deleted_at IS NULL
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                  'collapsed',
                  'rejected',
                  'demoted_source',
                  'hidden_from_ui'
              )
              AND coalesce(region.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'rejected'
            ORDER BY page.genre_id, page.region_id, page.confidence DESC, page.role
            ON CONFLICT (genre_id, region_id, mapping_type) DO UPDATE
            SET source_title = excluded.source_title,
                source_is_non_genre = excluded.source_is_non_genre,
                confidence = greatest(wg_region_node_mappings.confidence, excluded.confidence),
                raw_payload = wg_region_node_mappings.raw_payload || excluded.raw_payload,
                updated_at = now()
        """)
    )
    stats.mappings_upserted += result.rowcount or 0

    result = await conn.execute(
        text("""
            INSERT INTO wg_region_node_mappings (
                genre_id,
                region_id,
                mapping_type,
                source_title,
                source_is_non_genre,
                confidence,
                raw_payload,
                updated_at
            )
            SELECT DISTINCT ON (promoted.genre_id, promoted.region_id)
                promoted.genre_id,
                promoted.region_id,
                'region_promoted_genre',
                genre.wikipedia_title,
                genre.is_non_genre,
                0.9,
                jsonb_build_object('source', 'wg_region_promoted_genres'),
                now()
            FROM wg_region_promoted_genres promoted
            JOIN wg_genres genre ON genre.id = promoted.genre_id
            JOIN wg_regions region ON region.id = promoted.region_id
            WHERE genre.deleted_at IS NULL
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                  'collapsed',
                  'rejected',
                  'demoted_source',
                  'hidden_from_ui'
              )
              AND coalesce(region.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'rejected'
            ORDER BY promoted.genre_id, promoted.region_id
            ON CONFLICT (genre_id, region_id, mapping_type) DO UPDATE
            SET source_title = excluded.source_title,
                source_is_non_genre = excluded.source_is_non_genre,
                confidence = greatest(wg_region_node_mappings.confidence, excluded.confidence),
                raw_payload = wg_region_node_mappings.raw_payload || excluded.raw_payload,
                updated_at = now()
        """)
    )
    stats.mappings_upserted += result.rowcount or 0


async def _insert_title_region_node_mappings(
    conn: Any,
    stats: PureRegionGraphStats,
    *,
    sample_size: int,
) -> None:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT id, wikipedia_title, is_non_genre
                    FROM wg_genres
                    WHERE deleted_at IS NULL
                    ORDER BY wikipedia_title
                """)
            )
        )
        .mappings()
        .fetchall()
    )

    for row in rows:
        candidate = region_mapping_from_title(row["wikipedia_title"], row["id"])
        if not candidate:
            continue
        if candidate.mapping_type not in REGION_NODE_MAPPING_TYPES:
            stats.skipped_title_mappings += 1
            continue
        region_id = await _upsert_region_for_mapping(
            conn,
            region_name=candidate.region_name,
            source_title=row["wikipedia_title"],
            confidence=candidate.confidence,
        )
        if not region_id:
            stats.skipped_title_mappings += 1
            continue
        stats.regions_upserted += 1
        result = await conn.execute(
            text("""
                INSERT INTO wg_region_node_mappings (
                    genre_id,
                    region_id,
                    mapping_type,
                    source_title,
                    source_is_non_genre,
                    confidence,
                    raw_payload,
                    updated_at
                )
                VALUES (
                    :genre_id,
                    :region_id,
                    :mapping_type,
                    :source_title,
                    :source_is_non_genre,
                    :confidence,
                    jsonb_build_object('source', 'title_region_parser'),
                    now()
                )
                ON CONFLICT (genre_id, region_id, mapping_type) DO UPDATE
                SET source_title = excluded.source_title,
                    source_is_non_genre = excluded.source_is_non_genre,
                    confidence = greatest(wg_region_node_mappings.confidence, excluded.confidence),
                    raw_payload = wg_region_node_mappings.raw_payload || excluded.raw_payload,
                    updated_at = now()
            """),
            {
                "genre_id": candidate.genre_id,
                "region_id": region_id,
                "mapping_type": candidate.mapping_type,
                "source_title": row["wikipedia_title"],
                "source_is_non_genre": bool(row["is_non_genre"]),
                "confidence": candidate.confidence,
            },
        )
        stats.mappings_upserted += result.rowcount or 0
        _add_sample(
            stats,
            f"{row['wikipedia_title']} -> {candidate.region_name} ({candidate.mapping_type})",
            sample_size,
        )


async def _upsert_region_for_mapping(
    conn: Any,
    *,
    region_name: str,
    source_title: str,
    confidence: float,
) -> str | None:
    clean_name = clean_region_name(region_name)
    if not clean_name:
        return None
    region_id = normalize_region_id(clean_name)
    kind = infer_region_kind(clean_name, source_title)
    result = await conn.execute(
        text("""
            INSERT INTO wg_regions (
                id,
                canonical_name,
                kind,
                wikipedia_title,
                confidence,
                raw_payload,
                updated_at
            )
            VALUES (
                :region_id,
                :canonical_name,
                :kind,
                :wikipedia_title,
                :confidence,
                jsonb_build_object('source', 'pure_region_graph'),
                now()
            )
            ON CONFLICT (id) DO UPDATE
            SET canonical_name = excluded.canonical_name,
                kind = CASE
                    WHEN wg_regions.kind = 'unknown' THEN excluded.kind
                    ELSE wg_regions.kind
                END,
                wikipedia_title = COALESCE(wg_regions.wikipedia_title, excluded.wikipedia_title),
                confidence = greatest(wg_regions.confidence, excluded.confidence),
                raw_payload = wg_regions.raw_payload || excluded.raw_payload,
                updated_at = now()
        """),
        {
            "region_id": region_id,
            "canonical_name": clean_name,
            "kind": kind,
            "wikipedia_title": source_title,
            "confidence": confidence,
        },
    )
    return region_id if result.rowcount is not None else None


async def _insert_pure_region_relationships(
    conn: Any,
    stats: PureRegionGraphStats,
    *,
    sample_size: int,
) -> None:
    edge_rows = (
        (
            await conn.execute(
                text("""
                    WITH mapped_edges AS (
                        SELECT DISTINCT ON (
                            e.from_genre_id,
                            e.to_genre_id,
                            e.relation,
                            coalesce(e.evidence_relation, ''),
                            e.source,
                            from_map.region_id,
                            to_map.region_id
                        )
                            e.from_genre_id,
                            e.to_genre_id,
                            e.relation AS edge_relation,
                            e.evidence_relation,
                            e.source,
                            from_map.region_id AS source_from_region_id,
                            to_map.region_id AS source_to_region_id,
                            from_region.kind AS source_from_region_kind,
                            to_region.kind AS source_to_region_kind,
                            least(from_map.confidence, to_map.confidence) AS confidence,
                            from_map.mapping_type AS from_mapping_type,
                            to_map.mapping_type AS to_mapping_type
                        FROM wg_relationship_traversal_edges e
                        JOIN wg_region_node_mappings from_map
                          ON from_map.genre_id = e.from_genre_id
                        JOIN wg_region_node_mappings to_map
                          ON to_map.genre_id = e.to_genre_id
                        JOIN wg_regions from_region ON from_region.id = from_map.region_id
                        JOIN wg_regions to_region ON to_region.id = to_map.region_id
                        JOIN wg_genres from_genre ON from_genre.id = e.from_genre_id
                        JOIN wg_genres to_genre ON to_genre.id = e.to_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.relation = ANY(:region_edge_relations)
                          AND e.from_genre_id <> e.to_genre_id
                          AND from_map.region_id <> to_map.region_id
                          AND from_genre.deleted_at IS NULL
                          AND to_genre.deleted_at IS NULL
                        ORDER BY
                            e.from_genre_id,
                            e.to_genre_id,
                            e.relation,
                            coalesce(e.evidence_relation, ''),
                            e.source,
                            from_map.region_id,
                            to_map.region_id,
                            from_map.confidence DESC,
                            to_map.confidence DESC
                    )
                    SELECT *
                    FROM mapped_edges
                    ORDER BY edge_relation, source_from_region_id, source_to_region_id
                """),
                {"region_edge_relations": sorted(REGION_EDGE_RELATIONS)},
            )
        )
        .mappings()
        .fetchall()
    )

    for row in edge_rows:
        direction = (
            "inverted" if row["edge_relation"] in INVERTED_REGION_EDGE_RELATIONS else "forward"
        )
        if direction == "inverted":
            from_region_id = row["source_to_region_id"]
            to_region_id = row["source_from_region_id"]
            from_region_kind = row["source_to_region_kind"]
        else:
            from_region_id = row["source_from_region_id"]
            to_region_id = row["source_to_region_id"]
            from_region_kind = row["source_from_region_kind"]
        if from_region_id == to_region_id:
            continue
        relation = pure_region_relation_for_edge(
            source_edge_relation=row["edge_relation"],
            from_region_kind=from_region_kind,
            source_direction=direction,
        )
        result = await conn.execute(
            text("""
                INSERT INTO wg_pure_region_relationships (
                    from_region_id,
                    to_region_id,
                    relation,
                    source_from_genre_id,
                    source_to_genre_id,
                    source_edge_relation,
                    source_edge_evidence,
                    source_edge_source,
                    source_direction,
                    confidence,
                    raw_payload,
                    updated_at
                )
                VALUES (
                    :from_region_id,
                    :to_region_id,
                    :relation,
                    :source_from_genre_id,
                    :source_to_genre_id,
                    :source_edge_relation,
                    :source_edge_evidence,
                    :source_edge_source,
                    :source_direction,
                    :confidence,
                    jsonb_build_object(
                        'source', 'relationship_projection',
                        'from_mapping_type', CAST(:from_mapping_type AS text),
                        'to_mapping_type', CAST(:to_mapping_type AS text)
                    ),
                    now()
                )
                ON CONFLICT (
                    from_region_id,
                    to_region_id,
                    relation,
                    source_from_genre_id,
                    source_to_genre_id,
                    source_edge_relation,
                    coalesce(source_edge_evidence, ''),
                    source_edge_source,
                    source_direction
                )
                DO UPDATE
                SET confidence = greatest(
                        wg_pure_region_relationships.confidence,
                        excluded.confidence
                    ),
                    raw_payload = wg_pure_region_relationships.raw_payload || excluded.raw_payload,
                    updated_at = now()
            """),
            {
                "from_region_id": from_region_id,
                "to_region_id": to_region_id,
                "relation": relation,
                "source_from_genre_id": row["from_genre_id"],
                "source_to_genre_id": row["to_genre_id"],
                "source_edge_relation": row["edge_relation"],
                "source_edge_evidence": row["evidence_relation"],
                "source_edge_source": row["source"],
                "source_direction": direction,
                "confidence": row["confidence"],
                "from_mapping_type": row["from_mapping_type"],
                "to_mapping_type": row["to_mapping_type"],
            },
        )
        stats.relationships_upserted += result.rowcount or 0
        _add_sample(stats, f"{from_region_id} --{relation}--> {to_region_id}", sample_size)
