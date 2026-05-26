"""Phase 4 validation for staged regional relationship proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

REVIEW_MODEL = "deterministic-region-phase4-v1"


@dataclass(frozen=True)
class ReviewDecision:
    status: str
    reason: str


@dataclass
class RegionRelationshipReviewStats:
    region_rows_seen: int = 0
    region_rows_updated: int = 0
    region_accepted: int = 0
    region_rejected: int = 0
    region_needs_review: int = 0
    region_genre_rows_seen: int = 0
    region_genre_rows_updated: int = 0
    region_genre_accepted: int = 0
    region_genre_rejected: int = 0
    region_genre_needs_review: int = 0
    sample: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegionContainmentEdge:
    child_id: str
    child_name: str
    parent_id: str
    parent_name: str
    relation: str


@dataclass
class RegionPromotionAuditStats:
    accepted_region_relationships: int = 0
    accepted_region_genre_relationships: int = 0
    rejected_region_relationships: int = 0
    rejected_region_genre_relationships: int = 0
    pending_region_relationships: int = 0
    pending_region_genre_relationships: int = 0
    containment_cycles: int = 0
    accepted_container_region_edges: int = 0
    accepted_artifact_genre_edges: int = 0
    broad_region_genre_edges: int = 0
    duplicate_region_genre_pairs: int = 0
    promotion_ready: bool = False
    sample: list[str] = field(default_factory=list)


def is_container_region(name: str | None) -> bool:
    lower = (name or "").lower()
    return any(
        term in lower
        for term in (
            " by ",
            "dependent territories of ",
            "styles of music",
            "music genres",
        )
    )


def is_broad_region(name: str | None) -> bool:
    lower = (name or "").lower()
    return lower in {
        "africa",
        "asia",
        "europe",
        "north america",
        "south america",
        "oceania",
        "latin america",
        "caribbean",
        "middle eastern",
        "african diaspora",
    }


def is_country_like_region(name: str | None) -> bool:
    lower = (name or "").lower()
    return lower in {
        "argentina",
        "bahamas",
        "brazil",
        "chile",
        "colombia",
        "costa rica",
        "cuba",
        "denmark",
        "dominican republic",
        "finland",
        "haiti",
        "iceland",
        "iran",
        "jamaica",
        "mexico",
        "norway",
        "panama",
        "paraguay",
        "peru",
        "puerto rico",
        "sweden",
        "uruguay",
        "venezuela",
    }


def is_artifact_genre_title(title: str | None) -> bool:
    return (title or "").lower().startswith(("list of ", "category:"))


def list_context_region_from_payload(raw_payload: dict[str, Any]) -> str | None:
    direct_context = raw_payload.get("list_context_region")
    if isinstance(direct_context, str) and direct_context.strip():
        return direct_context

    review_payload = raw_payload.get("review")
    if not isinstance(review_payload, dict):
        return None
    nested_context = review_payload.get("list_context_region")
    if isinstance(nested_context, str) and nested_context.strip():
        return nested_context
    return None


def find_containment_cycles(edges: list[RegionContainmentEdge]) -> list[list[str]]:
    adjacency: dict[str, list[RegionContainmentEdge]] = {}
    name_by_id: dict[str, str] = {}
    for edge in edges:
        adjacency.setdefault(edge.child_id, []).append(edge)
        name_by_id[edge.child_id] = edge.child_name
        name_by_id[edge.parent_id] = edge.parent_name

    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    seen_cycle_keys: set[tuple[str, ...]] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            if node_id in stack:
                cycle_ids = stack[stack.index(node_id) :] + [node_id]
                key = tuple(cycle_ids)
                if key not in seen_cycle_keys:
                    seen_cycle_keys.add(key)
                    cycles.append([name_by_id.get(item, item) for item in cycle_ids])
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        stack.append(node_id)
        for edge in adjacency.get(node_id, []):
            visit(edge.parent_id)
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in list(adjacency):
        visit(node_id)
    return cycles


def review_region_relationship(row: dict[str, Any]) -> ReviewDecision:
    child = row["child_name"]
    parent = row["parent_name"]
    relation = row["relation"]
    source_type = row["source_type"]
    source = (row.get("source_title") or "").lower()
    raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}

    if is_container_region(child) or is_container_region(parent):
        return ReviewDecision(
            "needs_review",
            "Container-like region name; keep staged but require source-specific review.",
        )

    if source_type == "wikipedia_list" and list_context_region_from_payload(raw_payload):
        if relation == "part_of":
            return ReviewDecision(
                "accepted",
                "List worker accepted semantic row-context regional containment evidence.",
            )
        return ReviewDecision(
            "needs_review",
            "List-backed region hierarchy edge has unexpected relation.",
        )

    if source_type == "manual" and raw_payload.get("relation_source") == "regional_parent_alias":
        if relation == "part_of":
            return ReviewDecision(
                "accepted",
                "Deterministic regional-name alias accepted as hierarchy evidence.",
            )
        return ReviewDecision(
            "needs_review",
            "Manual regional-name alias has unexpected relation.",
        )

    if source_type != "wikipedia_category":
        return ReviewDecision(
            "needs_review",
            "Region hierarchy edge is not category-backed.",
        )

    if child == parent:
        return ReviewDecision("rejected", "Self-region edge.")

    if relation == "admin_parent":
        if " by " in source or "dependent territor" in source or source.startswith("category:music in "):
            return ReviewDecision(
                "accepted",
                "Category worker accepted explicit administrative/category parent evidence.",
            )
        return ReviewDecision(
            "needs_review",
            "Administrative relation lacks explicit by-country/by-city/dependent-territory evidence.",
        )

    if relation == "part_of":
        if is_broad_region(child) and is_broad_region(parent):
            return ReviewDecision(
                "accepted",
                "Category worker accepted broad-region containment evidence.",
            )
        return ReviewDecision(
            "accepted",
            "Category worker accepted direct regional category containment evidence.",
        )

    if relation in {"cultural_region_of", "diaspora_region_of", "historical_region_of"}:
        if (
            relation == "cultural_region_of"
            and child.lower() == "nordic"
            and is_country_like_region(parent)
        ):
            return ReviewDecision(
                "rejected",
                "Nordic category evidence points from a broader cultural region to member countries.",
            )
        if relation == "cultural_region_of" and "music of latin america" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Latin America parallel cultural parent evidence.",
            )
        if relation == "cultural_region_of" and "music of the caribbean" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Caribbean parallel cultural parent evidence.",
            )
        if relation == "cultural_region_of" and "latin american" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Latin America cultural category evidence.",
            )
        if relation == "cultural_region_of" and "caribbean music" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Caribbean cultural category evidence.",
            )
        if relation == "cultural_region_of" and "middle eastern" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Middle Eastern cultural category evidence.",
            )
        if relation == "cultural_region_of" and "north american" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted North American cultural category evidence.",
            )
        if relation == "cultural_region_of" and "celtic music" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted Celtic cultural category evidence.",
            )
        if relation == "diaspora_region_of" and "diaspora" in source:
            return ReviewDecision(
                "accepted",
                "Category worker accepted diaspora category parent evidence.",
            )
        if relation == "historical_region_of" and any(
            term in source for term in ("ancient", "medieval", "renaissance", "history")
        ):
            return ReviewDecision(
                "accepted",
                "Category worker accepted historical category parent evidence.",
            )
        return ReviewDecision(
            "needs_review",
            "Parallel region relation needs stronger source-specific review.",
        )

    return ReviewDecision("needs_review", "Unhandled region relation type.")


def review_region_genre_relationship(row: dict[str, Any]) -> ReviewDecision:
    region = row["region_name"]
    genre = row["genre_title"]
    relation = row["relation"]
    source_type = row["source_type"]
    source = (row.get("source_title") or "").lower()
    section = (row.get("source_section") or "").lower()
    extractor_model = row.get("extractor_model")

    if is_container_region(region):
        return ReviewDecision(
            "rejected",
            "Region-to-genre edge uses a container/list grouping as region.",
        )

    if genre.lower().startswith(("list of ", "category:")):
        return ReviewDecision(
            "rejected",
            "Region-to-genre edge targets a list/category artifact.",
        )

    if source_type == "wikipedia_category":
        return ReviewDecision(
            "accepted",
            "Category worker accepted direct regional category membership evidence.",
        )

    if source_type == "wikipedia_list":
        if section in {"see also", "references", "external links"}:
            return ReviewDecision(
                "needs_review",
                "List worker flagged generic list section for review.",
            )
        if relation in {
            "regional_scene",
            "local_scene",
            "traditional_region",
            "indigenous_region",
            "historical_region",
            "diaspora_region",
            "cultural_region",
        }:
            return ReviewDecision(
                "accepted",
                "List worker accepted source/list-section regional genre evidence.",
            )

    if source_type == "wikipedia_article":
        if section in {"see also", "references", "external links", "further reading"}:
            return ReviewDecision(
                "needs_review",
                "Article worker flagged generic article section for review.",
            )
        if extractor_model in {
            "deterministic-region-page-links-v1",
            "deterministic-region-page-links-v2",
        }:
            return ReviewDecision(
                "accepted",
                "Article worker accepted filtered exact-link evidence from regional music page.",
            )
        if source.startswith(("music of ", "music in ")) and section == genre.lower():
            return ReviewDecision(
                "accepted",
                "Article worker accepted exact genre section heading from regional music page.",
            )
        if (
            source.startswith(("music of ", "music in "))
            and section
            and any(
                term in section
                for term in (
                    "classical",
                    "dance",
                    "folk",
                    "genre",
                    "indigenous",
                    "local",
                    "popular",
                    "regional",
                    "scene",
                    "style",
                    "tradition",
                )
            )
        ):
            return ReviewDecision(
                "accepted",
                "Article worker accepted exact linked genre evidence from regional music page.",
            )

    if "music genres" in source or "folk music traditions" in source:
        return ReviewDecision(
            "accepted",
            "List worker accepted regional genre list evidence.",
        )

    return ReviewDecision(
        "needs_review",
        "Region-to-genre proposal needs source-specific review.",
    )


async def review_region_relationship_proposals(
    *,
    sample_size: int = 25,
) -> RegionRelationshipReviewStats:
    """Review Phase 3 staging rows by source type and relation shape."""
    await apply_migrations()
    stats = RegionRelationshipReviewStats()
    engine = get_engine()

    async with engine.begin() as conn:
        region_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            rel.id,
                            rel.relation,
                            rel.source_type,
                            rel.source_title,
                            child.canonical_name AS child_name,
                            parent.canonical_name AS parent_name,
                            rel.raw_payload
                        FROM wg_region_relationships rel
                        JOIN wg_regions child ON child.id = rel.from_region_id
                        JOIN wg_regions parent ON parent.id = rel.to_region_id
                        WHERE rel.status in ('proposed', 'needs_review')
                        ORDER BY rel.id
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.region_rows_seen = len(region_rows)
        for row in region_rows:
            row_dict = dict(row)
            decision = review_region_relationship(row_dict)
            if decision.status == "accepted":
                stats.region_accepted += 1
            elif decision.status == "rejected":
                stats.region_rejected += 1
            else:
                stats.region_needs_review += 1

            result = await conn.execute(
                text("""
                    UPDATE wg_region_relationships
                    SET status = :status,
                        review_reason = :review_reason,
                        reviewer_model = :reviewer_model,
                        raw_payload = raw_payload || jsonb_build_object(
                            'phase4_review',
                            jsonb_build_object(
                                'status', CAST(:status AS text),
                                'reason', CAST(:review_reason AS text),
                                'reviewer_model', CAST(:reviewer_model AS text)
                            )
                        ),
                        updated_at = now()
                    WHERE id = :id
                """),
                {
                    "id": row_dict["id"],
                    "status": decision.status,
                    "review_reason": decision.reason,
                    "reviewer_model": REVIEW_MODEL,
                },
            )
            stats.region_rows_updated += result.rowcount or 0
            add_sample(
                stats,
                f"region {decision.status}: {row_dict['child_name']} --{row_dict['relation']}--> {row_dict['parent_name']} ({decision.reason})",
                sample_size,
            )

        region_genre_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            rel.id,
                            rel.relation,
                            rel.source_type,
                            rel.source_title,
                            rel.source_section,
                            rel.raw_payload ->> 'extractor_model' AS extractor_model,
                            region.canonical_name AS region_name,
                            genre.wikipedia_title AS genre_title
                        FROM wg_region_genre_relationships rel
                        JOIN wg_regions region ON region.id = rel.region_id
                        JOIN wg_genres genre ON genre.id = rel.genre_id
                        WHERE rel.status in ('proposed', 'needs_review')
                        ORDER BY rel.id
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.region_genre_rows_seen = len(region_genre_rows)
        for row in region_genre_rows:
            row_dict = dict(row)
            decision = review_region_genre_relationship(row_dict)
            if decision.status == "accepted":
                stats.region_genre_accepted += 1
            elif decision.status == "rejected":
                stats.region_genre_rejected += 1
            else:
                stats.region_genre_needs_review += 1

            result = await conn.execute(
                text("""
                    UPDATE wg_region_genre_relationships
                    SET status = :status,
                        review_reason = :review_reason,
                        reviewer_model = :reviewer_model,
                        raw_payload = raw_payload || jsonb_build_object(
                            'phase4_review',
                            jsonb_build_object(
                                'status', CAST(:status AS text),
                                'reason', CAST(:review_reason AS text),
                                'reviewer_model', CAST(:reviewer_model AS text)
                            )
                        ),
                        updated_at = now()
                    WHERE id = :id
                """),
                {
                    "id": row_dict["id"],
                    "status": decision.status,
                    "review_reason": decision.reason,
                    "reviewer_model": REVIEW_MODEL,
                },
            )
            stats.region_genre_rows_updated += result.rowcount or 0
            add_sample(
                stats,
                f"region-genre {decision.status}: {row_dict['region_name']} --{row_dict['relation']}--> {row_dict['genre_title']} ({decision.reason})",
                sample_size,
            )

    logger.info(
        "region_relationship_review_complete",
        region_rows_seen=stats.region_rows_seen,
        region_accepted=stats.region_accepted,
        region_needs_review=stats.region_needs_review,
        region_genre_rows_seen=stats.region_genre_rows_seen,
        region_genre_accepted=stats.region_genre_accepted,
        region_genre_needs_review=stats.region_genre_needs_review,
    )
    return stats


async def audit_region_promotion_readiness(
    *,
    sample_size: int = 25,
) -> RegionPromotionAuditStats:
    """Audit accepted Phase 4 regional edges before any live promotion."""
    await apply_migrations()
    stats = RegionPromotionAuditStats()
    engine = get_engine()

    async with engine.begin() as conn:
        status_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT 'region' AS edge_kind, status, count(*) AS count
                        FROM wg_region_relationships
                        GROUP BY status
                        UNION ALL
                        SELECT 'region_genre' AS edge_kind, status, count(*) AS count
                        FROM wg_region_genre_relationships
                        WHERE relation NOT IN ('regional_style_mention', 'influence_or_context')
                        GROUP BY status
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        for row in status_rows:
            key = (row["edge_kind"], row["status"])
            count = int(row["count"])
            if key == ("region", "accepted"):
                stats.accepted_region_relationships = count
            elif key == ("region", "rejected"):
                stats.rejected_region_relationships = count
            elif key[0] == "region":
                stats.pending_region_relationships += count
            elif key == ("region_genre", "accepted"):
                stats.accepted_region_genre_relationships = count
            elif key == ("region_genre", "rejected"):
                stats.rejected_region_genre_relationships = count
            elif key[0] == "region_genre":
                stats.pending_region_genre_relationships += count

        containment_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            rel.from_region_id AS child_id,
                            child.canonical_name AS child_name,
                            rel.to_region_id AS parent_id,
                            parent.canonical_name AS parent_name,
                            rel.relation
                        FROM wg_region_relationships rel
                        JOIN wg_regions child ON child.id = rel.from_region_id
                        JOIN wg_regions parent ON parent.id = rel.to_region_id
                        WHERE rel.status = 'accepted'
                          AND rel.relation IN ('part_of', 'admin_parent')
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        cycles = find_containment_cycles(
            [
                RegionContainmentEdge(
                    child_id=row["child_id"],
                    child_name=row["child_name"],
                    parent_id=row["parent_id"],
                    parent_name=row["parent_name"],
                    relation=row["relation"],
                )
                for row in containment_rows
            ]
        )
        stats.containment_cycles = len(cycles)
        for cycle in cycles[:sample_size]:
            add_audit_sample(stats, f"cycle: {' -> '.join(cycle)}", sample_size)

        container_edges = (
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_relationships rel
                    JOIN wg_regions child ON child.id = rel.from_region_id
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    WHERE rel.status = 'accepted'
                      AND (
                          child.canonical_name ILIKE '% by %'
                          OR parent.canonical_name ILIKE '% by %'
                          OR child.canonical_name ILIKE '%styles of music%'
                          OR parent.canonical_name ILIKE '%styles of music%'
                          OR child.canonical_name ILIKE '%music genres%'
                          OR parent.canonical_name ILIKE '%music genres%'
                      )
                """)
            )
            or 0
        )
        stats.accepted_container_region_edges = int(container_edges)

        artifact_edges = (
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_genre_relationships rel
                    JOIN wg_genres genre ON genre.id = rel.genre_id
                    WHERE rel.status = 'accepted'
                      AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                      AND (
                          genre.wikipedia_title ILIKE 'List of %'
                          OR genre.wikipedia_title ILIKE 'Category:%'
                      )
                """)
            )
            or 0
        )
        stats.accepted_artifact_genre_edges = int(artifact_edges)

        broad_edges = (
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_genre_relationships rel
                    JOIN wg_regions region ON region.id = rel.region_id
                    WHERE rel.status = 'accepted'
                      AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                      AND lower(region.canonical_name) = ANY(:broad_regions)
                """),
                {
                    "broad_regions": [
                        "africa",
                        "asia",
                        "europe",
                        "north america",
                        "south america",
                        "oceania",
                        "latin america",
                        "caribbean",
                        "middle eastern",
                        "african diaspora",
                    ]
                },
            )
            or 0
        )
        stats.broad_region_genre_edges = int(broad_edges)

        duplicate_pairs = (
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM (
                        SELECT region_id, genre_id, relation
                        FROM wg_region_genre_relationships
                        WHERE status = 'accepted'
                          AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                        GROUP BY region_id, genre_id, relation
                        HAVING count(*) > 1
                    ) duplicates
                """)
            )
            or 0
        )
        stats.duplicate_region_genre_pairs = int(duplicate_pairs)

        if not stats.sample:
            rows = (
                (
                    await conn.execute(
                        text("""
                            SELECT region.canonical_name AS region_name,
                                   genre.wikipedia_title AS genre_title,
                                   rel.relation,
                                   rel.source_title
                            FROM wg_region_genre_relationships rel
                            JOIN wg_regions region ON region.id = rel.region_id
                            JOIN wg_genres genre ON genre.id = rel.genre_id
                            WHERE rel.status = 'accepted'
                              AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                            ORDER BY rel.confidence DESC, region.canonical_name, genre.wikipedia_title
                            LIMIT :limit
                        """),
                        {"limit": sample_size},
                    )
                )
                .mappings()
                .fetchall()
            )
            for row in rows:
                add_audit_sample(
                    stats,
                    f"accepted: {row['region_name']} --{row['relation']}--> {row['genre_title']} ({row['source_title']})",
                    sample_size,
                )

    stats.promotion_ready = (
        stats.pending_region_relationships == 0
        and stats.pending_region_genre_relationships == 0
        and stats.containment_cycles == 0
        and stats.accepted_container_region_edges == 0
        and stats.accepted_artifact_genre_edges == 0
    )
    return stats


def add_audit_sample(
    stats: RegionPromotionAuditStats,
    item: str,
    sample_size: int,
) -> None:
    if len(stats.sample) < sample_size:
        stats.sample.append(item)


def add_sample(
    stats: RegionRelationshipReviewStats,
    item: str,
    sample_size: int,
) -> None:
    if len(stats.sample) < sample_size:
        stats.sample.append(item)
