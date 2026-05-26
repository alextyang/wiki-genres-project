"""Production-readiness audits and deterministic cleanup for regional graph data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_graph import REGIONAL_STYLE_PARENT_ALIASES
from wiki_genres.loader.region_review import stable_key

logger = structlog.get_logger(__name__)

GRAPH_NON_PROMOTED_RELATIONS = {"regional_style_mention", "influence_or_context"}
REPORT_MODEL = "deterministic-region-production-audit-v1"
CLEANUP_MODEL = "deterministic-region-canonicalization-v1"
PRODUCTION_REVIEW_MODEL = "gpt-5.4-mini"
PRODUCTION_REVIEW_SOURCE_TITLE = "Region production review"
PRODUCTION_REVIEW_TYPES = {
    "zero_child_source_review",
    "parentless_region_review",
    "broad_region_genre_review",
    "invalid_region_title_review",
}
PRODUCTION_REVIEW_DECISIONS = {
    "keep",
    "collapse",
    "anchor",
    "extract_candidates",
    "reject",
    "rename",
    "needs_human",
    "keep_broad",
    "move_to_specific_regions",
    "inherit_from_children",
    "context_only",
}
PRODUCTION_REVIEW_CONFIDENCE = {"high", "medium", "low"}
BROAD_ALIAS_TARGETS = {
    "africa",
    "african diaspora",
    "caribbean",
    "celtic",
    "central america",
    "europe",
    "latin america",
    "middle east",
    "north america",
    "oceania",
    "south america",
    "united states",
}
BROAD_REGION_NAMES = [
    "africa",
    "asia",
    "europe",
    "north america",
    "south america",
    "oceania",
    "latin america",
    "caribbean",
    "middle east",
    "african diaspora",
]
APPROVED_ROOT_REGION_IDS = {
    "region-music",
    "region-africa",
    "region-americas",
    "region-asia",
    "region-europe",
    "region-north-america",
    "region-south-america",
    "region-oceania",
    "region-world",
}


@dataclass(frozen=True)
class AliasProxyCandidate:
    old_region_id: str
    old_name: str
    old_kind: str
    old_wikipedia_title: str | None
    target_region_id: str
    target_name: str
    target_kind: str
    promoted_genre_id: str | None = None
    promoted_title: str | None = None


@dataclass
class RegionProductionAuditStats:
    regions: int = 0
    promoted_regions: int = 0
    region_relationships: int = 0
    region_genre_relationships: int = 0
    accepted_region_relationships: int = 0
    accepted_graph_region_genre_relationships: int = 0
    candidate_rows: int = 0
    discovery_sources: int = 0
    zero_child_promoted_regions: int = 0
    parentless_accepted_regions: int = 0
    malformed_region_candidates: int = 0
    alias_proxy_candidates: int = 0
    invalid_region_titles: int = 0
    duplicate_region_genre_pairs: int = 0
    broad_region_genre_edges: int = 0
    graph_affecting_needs_review: int = 0
    pending_candidate_rows: int = 0
    report_path: str | None = None
    json_path: str | None = None
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    breakdowns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def production_ready(self) -> bool:
        return (
            self.graph_affecting_needs_review == 0
            and self.malformed_region_candidates == 0
            and self.alias_proxy_candidates == 0
            and self.invalid_region_titles == 0
            and self.zero_child_promoted_regions == 0
            and self.parentless_accepted_regions == 0
        )


@dataclass
class RegionCanonicalizationStats:
    candidates_seen: int = 0
    candidates_merged: int = 0
    genre_edges_added: int = 0
    sources_copied: int = 0
    music_pages_copied: int = 0
    region_edges_copied: int = 0
    region_genre_edges_copied: int = 0
    candidates_repointed: int = 0
    old_regions_deleted: int = 0
    dry_run: bool = False
    sample: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ZeroChildClassification:
    reason: str
    unresolved: bool


@dataclass
class RegionProductionReviewExportStats:
    output_dir: str
    rows_by_type: dict[str, int] = field(default_factory=dict)
    files_by_type: dict[str, str] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return sum(self.rows_by_type.values())


@dataclass
class RegionProductionReviewImportStats:
    input_path: str
    rows_seen: int = 0
    rows_imported: int = 0
    rows_needing_human: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class RegionProductionReviewApplyStats:
    decisions_seen: int = 0
    decisions_applied: int = 0
    decisions_needing_human: int = 0
    anchors_added: int = 0
    candidate_edges_added: int = 0
    relationships_demoted: int = 0
    regions_marked: int = 0
    regions_renamed: int = 0
    dry_run: bool = False
    sample: list[str] = field(default_factory=list)


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _is_valid_regional_title(title: str | None) -> bool:
    normalized = " ".join((title or "").split())
    if not normalized:
        return False
    if normalized.casefold().startswith("list of "):
        return False
    if re.fullmatch(r"Music of [^\s|<>][^|<>]*", normalized):
        return True
    return bool(re.fullmatch(r"[^\s|<>][^|<>]* music", normalized))


def _is_valid_review_decision(decision: str | None, review_type: str | None = None) -> bool:
    if decision not in PRODUCTION_REVIEW_DECISIONS:
        return False
    if review_type == "broad_region_genre_review":
        return decision in {
            "keep_broad",
            "move_to_specific_regions",
            "inherit_from_children",
            "context_only",
            "needs_human",
        }
    if review_type == "invalid_region_title_review":
        return decision in {"rename", "collapse", "reject", "needs_human"}
    if review_type == "parentless_region_review":
        return decision in {"anchor", "collapse", "keep", "reject", "needs_human"}
    if review_type == "zero_child_source_review":
        return decision in {"keep", "collapse", "extract_candidates", "reject", "needs_human"}
    return True


def _parent_preference_rank(*, kind: str | None, name: str | None = None) -> tuple[int, str]:
    normalized_kind = (kind or "unknown").casefold()
    rank_by_kind = {
        "country": 0,
        "territory": 1,
        "city": 2,
        "subregion": 3,
        "cultural_region": 4,
        "historical_region": 4,
        "language_region": 4,
        "diaspora_region": 5,
        "continent": 8,
        "unknown": 9,
    }
    return (rank_by_kind.get(normalized_kind, 9), _normalize(name))


def _classify_zero_child_promoted_region(row: dict[str, Any]) -> ZeroChildClassification:
    reason = str(row.get("reason") or "metadata_or_hierarchy_only")
    if reason not in {"city_scene_without_owned_children", "city_without_genre_candidates"}:
        return ZeroChildClassification(reason=reason, unresolved=False)
    staged_decision = row.get("staged_decision")
    raw_review = row.get("region_production_review")
    review_status = ""
    if isinstance(raw_review, dict):
        review_status = str(raw_review.get("status") or "")
    if reason == "reviewed_empty" or review_status == "reviewed_empty":
        return ZeroChildClassification(reason="reviewed_empty", unresolved=False)
    if isinstance(staged_decision, dict):
        decision = staged_decision.get("decision")
        explanation = staged_decision.get("explanation")
        if decision in {"keep", "keep_broad"} and explanation:
            return ZeroChildClassification(reason="reviewed_empty", unresolved=False)
    return ZeroChildClassification(reason=reason, unresolved=True)


def _is_style_proxy_title(title: str | None, alias: str) -> bool:
    normalized = _normalize(title)
    alias_norm = _normalize(alias)
    if not normalized or not alias_norm:
        return False
    if not normalized.startswith(alias_norm):
        return False
    return any(
        marker in normalized
        for marker in (
            "folk music",
            "styles of music",
            "traditional music",
            "music traditions",
        )
    )


def _is_safe_alias_proxy_target(candidate: AliasProxyCandidate) -> bool:
    if _normalize(candidate.target_name) in BROAD_ALIAS_TARGETS:
        return False
    return True


def relation_for_proxy_title(title: str | None) -> str:
    normalized = _normalize(title)
    if any(marker in normalized for marker in ("folk music", "traditional music", "music traditions")):
        return "traditional_region"
    return "regional_scene"


def proxy_genre_evidence(title: str | None, old_name: str, target_name: str) -> str:
    page = title or f"Music of {old_name}"
    return (
        f"{page} was canonicalized from regional proxy {old_name!r} "
        f"to canonical region {target_name!r}."
    )


async def find_alias_proxy_candidates() -> list[AliasProxyCandidate]:
    """Find demonym/style region nodes that should be folded into canonical regions."""
    await apply_migrations()
    aliases = [
        (alias, target)
        for alias, target in sorted(REGIONAL_STYLE_PARENT_ALIASES.items())
        if alias and target
    ]
    if not aliases:
        return []

    values_sql = ", ".join(
        f"(:alias_{idx}, :target_{idx})" for idx, _item in enumerate(aliases)
    )
    params: dict[str, str] = {}
    for idx, (alias, target) in enumerate(aliases):
        params[f"alias_{idx}"] = alias
        params[f"target_{idx}"] = target

    engine = get_engine()
    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text(f"""
                        WITH alias(alias_name, target_name) AS (
                            VALUES {values_sql}
                        )
                        SELECT
                            old.id AS old_region_id,
                            old.canonical_name AS old_name,
                            old.kind AS old_kind,
                            old.wikipedia_title AS old_wikipedia_title,
                            target.id AS target_region_id,
                            target.canonical_name AS target_name,
                            target.kind AS target_kind,
                            promoted.genre_id AS promoted_genre_id,
                            promoted.wikipedia_title AS promoted_title
                        FROM alias
                        JOIN wg_regions old
                          ON lower(old.canonical_name) = lower(alias.alias_name)
                        JOIN wg_regions target
                          ON lower(target.canonical_name) = lower(alias.target_name)
                        LEFT JOIN wg_region_promoted_genres promoted
                          ON promoted.region_id = old.id
                        WHERE old.id <> target.id
                        ORDER BY old.canonical_name
                    """),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

    candidates = [AliasProxyCandidate(**dict(row)) for row in rows]
    return [
        candidate
        for candidate in candidates
        if _is_style_proxy_title(candidate.old_wikipedia_title, candidate.old_name)
        and _is_safe_alias_proxy_target(candidate)
    ]


async def audit_region_production_readiness(
    *,
    output_dir: Path | None = None,
    sample_size: int = 25,
) -> RegionProductionAuditStats:
    """Build a reproducible production-readiness report for the regional graph."""
    await apply_migrations()
    stats = RegionProductionAuditStats()
    engine = get_engine()

    async with engine.begin() as conn:
        stats.regions = int(await conn.scalar(text("SELECT count(*) FROM wg_regions")) or 0)
        stats.promoted_regions = int(
            await conn.scalar(text("SELECT count(*) FROM wg_region_promoted_genres")) or 0
        )
        stats.region_relationships = int(
            await conn.scalar(text("SELECT count(*) FROM wg_region_relationships")) or 0
        )
        stats.region_genre_relationships = int(
            await conn.scalar(text("SELECT count(*) FROM wg_region_genre_relationships")) or 0
        )
        stats.candidate_rows = int(
            await conn.scalar(text("SELECT count(*) FROM wg_region_candidates")) or 0
        )
        stats.discovery_sources = int(
            await conn.scalar(text("SELECT count(*) FROM wg_region_discovery_sources")) or 0
        )
        stats.accepted_region_relationships = int(
            await conn.scalar(
                text("SELECT count(*) FROM wg_region_relationships WHERE status = 'accepted'")
            )
            or 0
        )
        stats.accepted_graph_region_genre_relationships = int(
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                """)
            )
            or 0
        )
        stats.graph_affecting_needs_review = int(
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_genre_relationships
                    WHERE status = 'needs_review'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                """)
            )
            or 0
        )
        stats.pending_candidate_rows = int(
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_candidates
                    WHERE status IN ('discovered', 'queued_for_crawl', 'needs_gpt_review')
                """)
            )
            or 0
        )
        stats.zero_child_promoted_regions = int(
            await conn.scalar(
                text("""
                    WITH owned AS (
                        SELECT region_id, count(*) AS owned_count
                        FROM wg_region_genre_relationships
                        WHERE status = 'accepted'
                          AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                        GROUP BY region_id
                    )
                    SELECT count(*)
                    FROM wg_region_promoted_genres promoted
                    JOIN wg_regions region ON region.id = promoted.region_id
                    LEFT JOIN owned USING (region_id)
                    WHERE coalesce(owned.owned_count, 0) = 0
                      AND region.kind = 'city'
                      AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') <> 'reviewed_empty'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_id = promoted.region_id
                          AND decision.review_type = 'zero_child_source_review'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                          AND decision.decision = 'keep'
                      )
                """)
            )
            or 0
        )
        stats.parentless_accepted_regions = int(
            await conn.scalar(
                text("""
                    WITH accepted_regions AS (
                        SELECT id
                        FROM wg_regions
                        WHERE EXISTS (
                            SELECT 1
                            FROM wg_region_promoted_genres promoted
                            WHERE promoted.region_id = wg_regions.id
                        )
                    ),
                    parented AS (
                        SELECT from_region_id AS region_id
                        FROM wg_region_relationships
                        WHERE status = 'accepted'
                    )
                    SELECT count(*)
                    FROM accepted_regions r
                    WHERE NOT EXISTS (
                        SELECT 1 FROM parented p WHERE p.region_id = r.id
                    )
                      AND r.id NOT IN (
                        'region-music',
                        'region-africa',
                        'region-americas',
                        'region-asia',
                        'region-europe',
                        'region-north-america',
                        'region-south-america',
                        'region-oceania',
                        'region-world'
                    )
                      AND coalesce(
                        (SELECT raw_payload #>> '{region_production_review,status}' FROM wg_regions where id = r.id),
                        ''
                      ) NOT IN ('approved_root', 'approved_superregion', 'collapsed', 'rejected', 'demoted_source')
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_id = r.id
                          AND decision.review_type = 'parentless_region_review'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                          AND decision.decision = 'keep'
                      )
                """)
            )
            or 0
        )
        promoted_title_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT promoted.wikipedia_title
                        FROM wg_region_promoted_genres promoted
                        JOIN wg_regions region ON region.id = promoted.region_id
                        WHERE coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                            'collapsed',
                            'rejected',
                            'demoted_source'
                        )
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.invalid_region_titles = sum(
            1 for row in promoted_title_rows if not _is_valid_regional_title(row["wikipedia_title"])
        )
        stats.duplicate_region_genre_pairs = int(
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
        stats.broad_region_genre_edges = int(
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_region_genre_relationships rel
                    JOIN wg_regions region ON region.id = rel.region_id
                    WHERE rel.status = 'accepted'
                      AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                      AND lower(region.canonical_name) = ANY(:broad_regions)
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_genre_relationship_id = rel.id
                          AND decision.review_type = 'broad_region_genre_review'
                          AND decision.decision = 'keep_broad'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                      )
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
                        "middle east",
                        "african diaspora",
                    ]
                },
            )
            or 0
        )

        malformed_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT id, canonical_name, kind, wikipedia_title
                        FROM wg_regions
                        WHERE canonical_name = lower(canonical_name)
                          AND canonical_name ~ '^[a-z]'
                          AND (
                            wikipedia_title ILIKE '%folk music%'
                            OR wikipedia_title ILIKE '%styles of music%'
                            OR wikipedia_title ILIKE 'List of % folk music traditions'
                          )
                        ORDER BY canonical_name
                        LIMIT :sample
                    """),
                    {"sample": max(sample_size, 1)},
                )
            )
            .mappings()
            .fetchall()
        )
        stats.samples["style_proxy_review_candidates"] = _rows_to_dicts(malformed_rows)
        stats.malformed_region_candidates = len(await find_alias_proxy_candidates())
        stats.alias_proxy_candidates = stats.malformed_region_candidates

        sample_queries = {
            "zero_child_promoted_regions": """
                WITH owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                )
                SELECT r.id, r.canonical_name, r.kind, promoted.wikipedia_title
                FROM wg_region_promoted_genres promoted
                JOIN wg_regions r ON r.id = promoted.region_id
                LEFT JOIN owned USING (region_id)
                WHERE coalesce(owned.owned_count, 0) = 0
                  AND r.kind = 'city'
                  AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') <> 'reviewed_empty'
                ORDER BY r.kind, promoted.wikipedia_title
                LIMIT :sample
            """,
            "parentless_promoted_regions": """
                SELECT r.id, r.canonical_name, r.kind, promoted.wikipedia_title
                FROM wg_region_promoted_genres promoted
                JOIN wg_regions r ON r.id = promoted.region_id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM wg_region_relationships rel
                    WHERE rel.status = 'accepted'
                      AND rel.from_region_id = r.id
                )
                  AND r.id NOT IN (
                    'region-music',
                    'region-africa',
                    'region-americas',
                    'region-asia',
                    'region-europe',
                    'region-north-america',
                    'region-south-america',
                    'region-oceania',
                    'region-world'
                  )
                  AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                    'approved_root',
                    'approved_superregion',
                    'collapsed',
                    'rejected',
                    'demoted_source'
                  )
                ORDER BY r.kind, promoted.wikipedia_title
                LIMIT :sample
            """,
            "duplicate_region_genre_pairs": """
                SELECT region.canonical_name AS region_name,
                       genre.wikipedia_title AS genre_title,
                       rel.relation,
                       count(*) AS duplicate_rows
                FROM wg_region_genre_relationships rel
                JOIN wg_regions region ON region.id = rel.region_id
                JOIN wg_genres genre ON genre.id = rel.genre_id
                WHERE rel.status = 'accepted'
                  AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                GROUP BY region.canonical_name, genre.wikipedia_title, rel.relation
                HAVING count(*) > 1
                ORDER BY duplicate_rows DESC, region.canonical_name, genre.wikipedia_title
                LIMIT :sample
            """,
            "broad_region_genre_edges": """
                SELECT region.canonical_name AS region_name,
                       genre.wikipedia_title AS genre_title,
                       rel.relation,
                       rel.source_type,
                       rel.source_title
                FROM wg_region_genre_relationships rel
                JOIN wg_regions region ON region.id = rel.region_id
                JOIN wg_genres genre ON genre.id = rel.genre_id
                WHERE rel.status = 'accepted'
                  AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                  AND lower(region.canonical_name) = ANY(:broad_regions)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM wg_region_production_review_decisions decision
                    WHERE decision.region_genre_relationship_id = rel.id
                      AND decision.review_type = 'broad_region_genre_review'
                      AND decision.decision = 'keep_broad'
                      AND decision.confidence = 'high'
                      AND decision.status IN ('imported', 'applied')
                  )
                ORDER BY region.canonical_name, genre.wikipedia_title
                LIMIT :sample
            """,
        }
        for key, sql in sample_queries.items():
            params: dict[str, Any] = {"sample": max(sample_size, 1)}
            if "broad_regions" in sql:
                params["broad_regions"] = [
                    "africa",
                    "asia",
                    "europe",
                    "north america",
                    "south america",
                    "oceania",
                    "latin america",
                    "caribbean",
                    "middle east",
                    "african diaspora",
                ]
            rows = (await conn.execute(text(sql), params)).mappings().fetchall()
            stats.samples[key] = _rows_to_dicts(rows)

        invalid_title_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT r.id, r.canonical_name, r.kind, promoted.wikipedia_title
                        FROM wg_region_promoted_genres promoted
                        JOIN wg_regions r ON r.id = promoted.region_id
                        WHERE coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                            'collapsed',
                            'rejected',
                            'demoted_source'
                        )
                        ORDER BY r.canonical_name
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.samples["invalid_region_titles"] = [
            dict(row)
            for row in invalid_title_rows
            if not _is_valid_regional_title(row["wikipedia_title"])
        ][: max(sample_size, 1)]

        breakdown_queries = {
            "region_genre_by_source_type": """
                SELECT source_type,
                       count(*) AS rows,
                       count(*) FILTER (WHERE status = 'accepted') AS accepted,
                       count(*) FILTER (
                         WHERE relation IN ('regional_style_mention', 'influence_or_context')
                       ) AS non_promoted
                FROM wg_region_genre_relationships
                GROUP BY source_type
                ORDER BY rows DESC
            """,
            "region_candidate_status_type": """
                SELECT status, candidate_type, count(*) AS rows
                FROM wg_region_candidates
                GROUP BY status, candidate_type
                ORDER BY status, candidate_type
            """,
            "region_genre_relation_counts": """
                SELECT relation, count(*) AS rows
                FROM wg_region_genre_relationships
                GROUP BY relation
                ORDER BY rows DESC, relation
            """,
            "region_relation_counts": """
                SELECT relation, count(*) AS rows
                FROM wg_region_relationships
                GROUP BY relation
                ORDER BY rows DESC, relation
            """,
            "zero_child_promoted_region_reasons": """
                WITH owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                )
                SELECT
                    CASE
                        WHEN region.kind = 'city'
                        THEN 'city_scene_without_owned_children'
                        WHEN promoted.wikipedia_title !~* '^Music (of|in) '
                        THEN 'regional_style_or_traditional_leaf'
                        WHEN EXISTS (
                            SELECT 1
                            FROM wg_region_genre_relationships rel
                            WHERE rel.region_id = region.id
                              AND rel.status = 'accepted'
                              AND rel.relation IN ('regional_style_mention', 'influence_or_context')
                        )
                        THEN 'only_context_or_style_mentions'
                        WHEN EXISTS (
                            SELECT 1
                            FROM wg_region_genre_relationships rel
                            WHERE rel.region_id = region.id
                        )
                        THEN 'no_accepted_owned_children'
                        WHEN EXISTS (
                            SELECT 1
                            FROM wg_region_sources source
                            WHERE source.region_id = region.id
                        )
                        THEN 'source_without_genre_candidates'
                        ELSE 'metadata_or_hierarchy_only'
                    END AS reason,
                    count(*) AS rows
                FROM wg_region_promoted_genres promoted
                JOIN wg_regions region ON region.id = promoted.region_id
                LEFT JOIN owned USING (region_id)
                WHERE coalesce(owned.owned_count, 0) = 0
                  AND region.kind = 'city'
                  AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') <> 'reviewed_empty'
                GROUP BY reason
                ORDER BY rows DESC, reason
            """,
            "region_production_review_decisions": """
                SELECT review_type, decision, confidence, status, count(*) AS rows
                FROM wg_region_production_review_decisions
                GROUP BY review_type, decision, confidence, status
                ORDER BY review_type, decision, confidence, status
            """,
        }
        for key, sql in breakdown_queries.items():
            rows = (await conn.execute(text(sql))).mappings().fetchall()
            stats.breakdowns[key] = _rows_to_dicts(rows)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "region_production_audit.json"
        report_path = output_dir / "region_production_audit.md"
        json_path.write_text(json.dumps(_stats_to_dict(stats), indent=2, sort_keys=True))
        report_path.write_text(_render_markdown_report(stats))
        stats.json_path = str(json_path)
        stats.report_path = str(report_path)

    logger.info(
        "region_production_audit_complete",
        production_ready=stats.production_ready,
        regions=stats.regions,
        promoted_regions=stats.promoted_regions,
        zero_child_promoted_regions=stats.zero_child_promoted_regions,
        malformed_region_candidates=stats.malformed_region_candidates,
    )
    return stats


async def canonicalize_region_alias_proxies(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
) -> RegionCanonicalizationStats:
    """Merge deterministic demonym/style proxy regions into canonical regions."""
    await apply_migrations()
    candidates = await find_alias_proxy_candidates()
    stats = RegionCanonicalizationStats(candidates_seen=len(candidates), dry_run=dry_run)
    if dry_run:
        stats.sample = [
            f"{candidate.old_name} -> {candidate.target_name} ({candidate.old_wikipedia_title})"
            for candidate in candidates[:sample_size]
        ]
        return stats

    engine = get_engine()
    async with engine.begin() as conn:
        for candidate in candidates:
            relation = relation_for_proxy_title(candidate.promoted_title or candidate.old_wikipedia_title)
            canonical_genre_id = await _canonicalize_proxy_genre_row(conn, candidate)
            if canonical_genre_id:
                result = await conn.execute(
                    text("""
                        INSERT INTO wg_region_genre_relationships (
                            region_id,
                            genre_id,
                            relation,
                            source_type,
                            source_title,
                            evidence_text,
                            confidence,
                            status,
                            review_reason,
                            reviewer_model,
                            raw_payload
                        )
                        VALUES (
                            :target_region_id,
                            :genre_id,
                            :relation,
                            'manual',
                            'Region alias canonicalization',
                            :evidence_text,
                            0.95,
                            'accepted',
                            'Deterministic cleanup: demonym/style proxy page belongs under canonical region.',
                            :reviewer_model,
                            jsonb_build_object(
                                'cleanup_model', CAST(:reviewer_model AS text),
                                'merged_from_region_id', CAST(:old_region_id AS text),
                                'merged_from_region_name', CAST(:old_name AS text)
                            )
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "target_region_id": candidate.target_region_id,
                        "genre_id": canonical_genre_id,
                        "relation": relation,
                        "evidence_text": proxy_genre_evidence(
                            candidate.old_wikipedia_title or candidate.promoted_title,
                            candidate.old_name,
                            candidate.target_name,
                        ),
                        "reviewer_model": CLEANUP_MODEL,
                        "old_region_id": candidate.old_region_id,
                        "old_name": candidate.old_name,
                    },
                )
                stats.genre_edges_added += result.rowcount or 0

            stats.sources_copied += await _copy_region_sources(conn, candidate)
            stats.music_pages_copied += await _copy_region_music_pages(
                conn,
                candidate,
                canonical_genre_id=canonical_genre_id,
            )
            stats.region_edges_copied += await _copy_region_relationships(conn, candidate)
            stats.region_genre_edges_copied += await _copy_region_genre_relationships(
                conn,
                candidate,
                canonical_genre_id=canonical_genre_id,
            )

            result = await conn.execute(
                text("""
                    UPDATE wg_region_candidates
                    SET suggested_region_id = :target_region_id,
                        suggested_region_name = :target_name,
                        review_reason = coalesce(review_reason, '') ||
                            ' Deterministic cleanup: repointed demonym/style proxy to canonical region.',
                        raw_payload = raw_payload || jsonb_build_object(
                            'canonicalized_region_proxy',
                            jsonb_build_object(
                                'cleanup_model', CAST(:reviewer_model AS text),
                                'old_region_id', CAST(:old_region_id AS text),
                                'old_region_name', CAST(:old_name AS text),
                                'target_region_id', CAST(:target_region_id AS text),
                                'target_region_name', CAST(:target_name AS text)
                            )
                        ),
                        updated_at = now()
                    WHERE suggested_region_id = :old_region_id
                """),
                {
                    "target_region_id": candidate.target_region_id,
                    "target_name": candidate.target_name,
                    "old_region_id": candidate.old_region_id,
                    "old_name": candidate.old_name,
                    "reviewer_model": CLEANUP_MODEL,
                },
            )
            stats.candidates_repointed += result.rowcount or 0

            result = await conn.execute(
                text("DELETE FROM wg_regions WHERE id = :old_region_id"),
                {"old_region_id": candidate.old_region_id},
            )
            stats.old_regions_deleted += result.rowcount or 0
            await _delete_unreferenced_proxy_genre(conn, candidate)
            stats.candidates_merged += 1
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{candidate.old_name} -> {candidate.target_name} "
                    f"({candidate.promoted_title or candidate.old_wikipedia_title})"
                )

    logger.info(
        "region_alias_proxy_canonicalization_complete",
        candidates_seen=stats.candidates_seen,
        candidates_merged=stats.candidates_merged,
        genre_edges_added=stats.genre_edges_added,
        old_regions_deleted=stats.old_regions_deleted,
    )
    return stats


async def export_region_production_review_batches(
    *,
    output_dir: Path = Path("tmp/region_production_reviews"),
    review_type: str | None = None,
    limit: int | None = None,
    sample_size: int = 25,
) -> RegionProductionReviewExportStats:
    """Export unresolved production audit buckets as GPT-5.4-mini JSONL queues."""
    await apply_migrations()
    selected_types = [review_type] if review_type else sorted(PRODUCTION_REVIEW_TYPES)
    unknown_types = [item for item in selected_types if item not in PRODUCTION_REVIEW_TYPES]
    if unknown_types:
        raise ValueError(f"unknown production review type(s): {', '.join(unknown_types)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stats = RegionProductionReviewExportStats(output_dir=str(output_dir))
    engine = get_engine()
    async with engine.begin() as conn:
        for selected_type in selected_types:
            rows = await _load_production_review_export_rows(
                conn,
                selected_type,
                limit=limit,
                sample_size=sample_size,
            )
            output_path = output_dir / f"{selected_type}.jsonl"
            with output_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            batch_key = stable_key(
                "region-production-review",
                selected_type,
                str(output_path),
            )
            await conn.execute(
                text("""
                    INSERT INTO wg_region_production_review_batches (
                        batch_key,
                        review_type,
                        output_path,
                        rows_exported,
                        status,
                        reviewer_model,
                        raw_payload,
                        updated_at
                    )
                    VALUES (
                        :batch_key,
                        :review_type,
                        :output_path,
                        :rows_exported,
                        'exported',
                        :reviewer_model,
                        jsonb_build_object(
                            'sample_size', CAST(:sample_size AS integer),
                            'limit', CAST(:limit_value AS integer)
                        ),
                        now()
                    )
                    ON CONFLICT (batch_key) DO UPDATE
                    SET output_path = excluded.output_path,
                        rows_exported = excluded.rows_exported,
                        status = 'exported',
                        reviewer_model = excluded.reviewer_model,
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                """),
                {
                    "batch_key": batch_key,
                    "review_type": selected_type,
                    "output_path": str(output_path),
                    "rows_exported": len(rows),
                    "reviewer_model": PRODUCTION_REVIEW_MODEL,
                    "sample_size": sample_size,
                    "limit_value": limit or 0,
                },
            )
            stats.rows_by_type[selected_type] = len(rows)
            stats.files_by_type[selected_type] = str(output_path)
    return stats


async def import_region_production_review_decisions(
    *,
    input_path: Path,
    batch_key: str | None = None,
    reviewer_model: str = PRODUCTION_REVIEW_MODEL,
) -> RegionProductionReviewImportStats:
    """Import reviewed JSONL decisions into staging tables without graph mutation."""
    await apply_migrations()
    stats = RegionProductionReviewImportStats(input_path=str(input_path))
    engine = get_engine()
    async with engine.begin() as conn:
        for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            stats.rows_seen += 1
            try:
                payload = json.loads(line)
                review_payload = payload.get("review") if isinstance(payload.get("review"), dict) else payload
                normalized = _normalize_review_payload(payload, review_payload, batch_key, reviewer_model)
            except ValueError as exc:
                stats.rows_rejected += 1
                stats.errors.append(f"line {line_number}: {exc}")
                continue
            status = "needs_human"
            if normalized["decision"] != "needs_human" and normalized["confidence"] == "high":
                status = "imported"
            elif normalized["decision"] == "reject" and normalized["confidence"] == "high":
                status = "imported"
            await conn.execute(
                text("""
                    INSERT INTO wg_region_production_review_decisions (
                        decision_key,
                        batch_key,
                        review_type,
                        subject_key,
                        region_id,
                        region_genre_relationship_id,
                        genre_id,
                        decision,
                        confidence,
                        explanation,
                        target_parents,
                        candidate_genres,
                        title_replacement,
                        status,
                        reviewer_model,
                        raw_payload,
                        updated_at
                    )
                    VALUES (
                        :decision_key,
                        :batch_key,
                        :review_type,
                        :subject_key,
                        :region_id,
                        :region_genre_relationship_id,
                        :genre_id,
                        :decision,
                        :confidence,
                        :explanation,
                        CAST(:target_parents AS jsonb),
                        CAST(:candidate_genres AS jsonb),
                        :title_replacement,
                        :status,
                        :reviewer_model,
                        CAST(:raw_payload AS jsonb),
                        now()
                    )
                    ON CONFLICT (decision_key) DO UPDATE
                    SET decision = excluded.decision,
                        confidence = excluded.confidence,
                        explanation = excluded.explanation,
                        target_parents = excluded.target_parents,
                        candidate_genres = excluded.candidate_genres,
                        title_replacement = excluded.title_replacement,
                        status = excluded.status,
                        reviewer_model = excluded.reviewer_model,
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                """),
                normalized | {
                    "target_parents": json.dumps(normalized["target_parents"], sort_keys=True),
                    "candidate_genres": json.dumps(normalized["candidate_genres"], sort_keys=True),
                    "raw_payload": json.dumps(payload, sort_keys=True, default=str),
                    "status": status,
                },
            )
            if status == "needs_human":
                stats.rows_needing_human += 1
            else:
                stats.rows_imported += 1
        if batch_key:
            await conn.execute(
                text("""
                    UPDATE wg_region_production_review_batches
                    SET status = 'imported',
                        updated_at = now()
                    WHERE batch_key = :batch_key
                """),
                {"batch_key": batch_key},
            )
    return stats


async def apply_region_production_review_decisions(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
) -> RegionProductionReviewApplyStats:
    """Apply deterministic high-confidence production review decisions."""
    await apply_migrations()
    stats = RegionProductionReviewApplyStats(dry_run=dry_run)
    engine = get_engine()
    async with engine.begin() as conn:
        decisions = (
            (
                await conn.execute(
                    text("""
                        SELECT *
                        FROM wg_region_production_review_decisions
                        WHERE status = 'imported'
                          AND confidence = 'high'
                        ORDER BY review_type, decision_key
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.decisions_seen = len(decisions)
        for decision_row in decisions:
            decision = dict(decision_row)
            applied = False
            if dry_run:
                applied = True
            elif decision["review_type"] == "zero_child_source_review":
                applied = await _apply_zero_child_review(conn, decision, stats)
            elif decision["review_type"] == "parentless_region_review":
                applied = await _apply_parentless_review(conn, decision, stats)
            elif decision["review_type"] == "broad_region_genre_review":
                applied = await _apply_broad_region_genre_review(conn, decision, stats)
            elif decision["review_type"] == "invalid_region_title_review":
                applied = await _apply_invalid_title_review(conn, decision, stats)

            if applied:
                stats.decisions_applied += 1
                if len(stats.sample) < sample_size:
                    stats.sample.append(
                        f"{decision['review_type']}:{decision['decision']}:{decision['subject_key']}"
                    )
                if not dry_run:
                    await conn.execute(
                        text("""
                            UPDATE wg_region_production_review_decisions
                            SET status = 'applied',
                                applied_at = now(),
                                updated_at = now()
                            WHERE decision_key = :decision_key
                        """),
                        {"decision_key": decision["decision_key"]},
                    )
            else:
                stats.decisions_needing_human += 1
                if not dry_run:
                    await conn.execute(
                        text("""
                            UPDATE wg_region_production_review_decisions
                            SET status = 'needs_human',
                                updated_at = now()
                            WHERE decision_key = :decision_key
                        """),
                        {"decision_key": decision["decision_key"]},
                    )
    return stats


async def _load_production_review_export_rows(
    conn: Any,
    review_type: str,
    *,
    limit: int | None,
    sample_size: int,
) -> list[dict[str, Any]]:
    if review_type == "zero_child_source_review":
        rows = await _load_zero_child_review_rows(conn, limit=limit)
    elif review_type == "parentless_region_review":
        rows = await _load_parentless_region_review_rows(conn, limit=limit)
    elif review_type == "broad_region_genre_review":
        rows = await _load_broad_region_genre_review_rows(conn, limit=limit)
    elif review_type == "invalid_region_title_review":
        rows = await _load_invalid_title_review_rows(conn, limit=limit)
    else:
        raise ValueError(f"unknown production review type: {review_type}")
    return [
        _with_review_instructions(row, review_type=review_type, sample_size=sample_size)
        for row in rows
    ]


async def _load_zero_child_review_rows(conn: Any, *, limit: int | None) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    WITH owned AS (
                        SELECT region_id, count(*) AS owned_count
                        FROM wg_region_genre_relationships
                        WHERE status = 'accepted'
                          AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                        GROUP BY region_id
                    ),
                    zero_child AS (
                        SELECT
                            region.id AS region_id,
                            region.canonical_name,
                            region.display_title,
                            region.kind,
                            region.wikipedia_title,
                            region.raw_payload #> '{region_production_review}' AS region_production_review,
                            CASE
                                WHEN region.kind = 'city'
                                THEN 'city_scene_without_owned_children'
                                WHEN EXISTS (
                                    SELECT 1
                                    FROM wg_region_sources source
                                    WHERE source.region_id = region.id
                                )
                                THEN 'source_without_genre_candidates'
                                ELSE 'other_zero_child'
                            END AS reason
                        FROM wg_region_promoted_genres promoted
                        JOIN wg_regions region ON region.id = promoted.region_id
                        LEFT JOIN owned ON owned.region_id = region.id
                        WHERE coalesce(owned.owned_count, 0) = 0
                          AND region.kind = 'city'
                    )
                    SELECT
                        zero_child.*,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'source_type', source.source_type,
                                'source_url', source.source_url,
                                'source_title', source.source_title,
                                'source_section', source.source_section,
                                'evidence_text', source.evidence_text,
                                'confidence', source.confidence
                            ) ORDER BY source.confidence DESC, source.source_title)
                            FROM wg_region_sources source
                            WHERE source.region_id = zero_child.region_id
                        ), '[]'::jsonb) AS sources,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'parent_region_id', parent.id,
                                'parent_name', parent.canonical_name,
                                'parent_kind', parent.kind,
                                'relation', rel.relation,
                                'source_title', rel.source_title
                            ) ORDER BY parent.kind, parent.canonical_name)
                            FROM wg_region_relationships rel
                            JOIN wg_regions parent ON parent.id = rel.to_region_id
                            WHERE rel.from_region_id = zero_child.region_id
                              AND rel.status = 'accepted'
                        ), '[]'::jsonb) AS current_parents,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'genre_id', genre.id,
                                'genre_title', genre.wikipedia_title,
                                'relation', rel.relation,
                                'status', rel.status,
                                'evidence_text', rel.evidence_text,
                                'source_title', rel.source_title
                            ) ORDER BY rel.status, genre.wikipedia_title)
                            FROM wg_region_genre_relationships rel
                            JOIN wg_genres genre ON genre.id = rel.genre_id
                            WHERE rel.region_id = zero_child.region_id
                        ), '[]'::jsonb) AS current_genre_links
                    FROM zero_child
                    WHERE reason IN ('source_without_genre_candidates', 'city_scene_without_owned_children')
                      AND coalesce(region_production_review ->> 'status', '') <> 'reviewed_empty'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_id = zero_child.region_id
                          AND decision.review_type = 'zero_child_source_review'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                      )
                    ORDER BY reason, canonical_name
                    LIMIT :limit_value
                """),
                {"limit_value": limit or 1000000},
            )
        )
        .mappings()
        .fetchall()
    )
    return [_review_subject_dict(row, "zero_child_source_review", row["region_id"]) for row in rows]


async def _load_parentless_region_review_rows(conn: Any, *, limit: int | None) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT
                        region.id AS region_id,
                        region.canonical_name,
                        region.display_title,
                        region.kind,
                        region.wikipedia_title,
                        region.raw_payload #> '{region_production_review}' AS region_production_review,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'child_region_id', child.id,
                                'child_name', child.canonical_name,
                                'child_kind', child.kind,
                                'relation', rel.relation
                            ) ORDER BY child.kind, child.canonical_name)
                            FROM wg_region_relationships rel
                            JOIN wg_regions child ON child.id = rel.from_region_id
                            WHERE rel.to_region_id = region.id
                              AND rel.status = 'accepted'
                        ), '[]'::jsonb) AS child_regions,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'genre_id', genre.id,
                                'genre_title', genre.wikipedia_title,
                                'relation', rel.relation,
                                'source_title', rel.source_title
                            ) ORDER BY genre.wikipedia_title)
                            FROM wg_region_genre_relationships rel
                            JOIN wg_genres genre ON genre.id = rel.genre_id
                            WHERE rel.region_id = region.id
                              AND rel.status = 'accepted'
                              AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                        ), '[]'::jsonb) AS owned_genres,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'source_type', source.source_type,
                                'source_title', source.source_title,
                                'source_url', source.source_url,
                                'evidence_text', source.evidence_text
                            ) ORDER BY source.source_type, source.source_title)
                            FROM wg_region_sources source
                            WHERE source.region_id = region.id
                        ), '[]'::jsonb) AS sources
                    FROM wg_region_promoted_genres promoted
                    JOIN wg_regions region ON region.id = promoted.region_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM wg_region_relationships rel
                        WHERE rel.status = 'accepted'
                          AND rel.from_region_id = region.id
                    )
                      AND region.id <> ALL(:approved_roots)
                      AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'approved_root',
                        'approved_superregion',
                        'collapsed',
                        'rejected',
                        'demoted_source'
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_id = region.id
                          AND decision.review_type = 'parentless_region_review'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                      )
                    ORDER BY region.kind, region.canonical_name
                    LIMIT :limit_value
                """),
                {
                    "approved_roots": sorted(APPROVED_ROOT_REGION_IDS),
                    "limit_value": limit or 1000000,
                },
            )
        )
        .mappings()
        .fetchall()
    )
    return [_review_subject_dict(row, "parentless_region_review", row["region_id"]) for row in rows]


async def _load_broad_region_genre_review_rows(conn: Any, *, limit: int | None) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT
                        rel.id AS region_genre_relationship_id,
                        region.id AS region_id,
                        region.canonical_name AS region_name,
                        region.kind AS region_kind,
                        region.wikipedia_title AS region_title,
                        genre.id AS genre_id,
                        genre.wikipedia_title AS genre_title,
                        rel.relation,
                        rel.source_type,
                        rel.source_title,
                        rel.source_section,
                        rel.evidence_text,
                        rel.confidence,
                        rel.review_reason
                    FROM wg_region_genre_relationships rel
                    JOIN wg_regions region ON region.id = rel.region_id
                    JOIN wg_genres genre ON genre.id = rel.genre_id
                    WHERE rel.status = 'accepted'
                      AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                      AND lower(region.canonical_name) = ANY(:broad_regions)
                      AND NOT EXISTS (
                        SELECT 1
                        FROM wg_region_production_review_decisions decision
                        WHERE decision.region_genre_relationship_id = rel.id
                          AND decision.review_type = 'broad_region_genre_review'
                          AND decision.decision = 'keep_broad'
                          AND decision.confidence = 'high'
                          AND decision.status IN ('imported', 'applied')
                      )
                    ORDER BY region.canonical_name, genre.wikipedia_title
                    LIMIT :limit_value
                """),
                {
                    "broad_regions": BROAD_REGION_NAMES,
                    "limit_value": limit or 1000000,
                },
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        _review_subject_dict(
            row,
            "broad_region_genre_review",
            f"{row['region_id']}:{row['region_genre_relationship_id']}",
        )
        for row in rows
    ]


async def _load_invalid_title_review_rows(conn: Any, *, limit: int | None) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT
                        region.id AS region_id,
                        region.canonical_name,
                        region.display_title,
                        region.kind,
                        region.wikipedia_title,
                        promoted.genre_id,
                        promoted.wikipedia_title AS promoted_title,
                        coalesce((
                            SELECT jsonb_agg(jsonb_build_object(
                                'source_type', source.source_type,
                                'source_title', source.source_title,
                                'source_url', source.source_url,
                                'evidence_text', source.evidence_text
                            ) ORDER BY source.source_type, source.source_title)
                            FROM wg_region_sources source
                            WHERE source.region_id = region.id
                        ), '[]'::jsonb) AS sources
                    FROM wg_region_promoted_genres promoted
                    JOIN wg_regions region ON region.id = promoted.region_id
                    WHERE coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'collapsed',
                        'rejected',
                        'demoted_source'
                    )
                    ORDER BY region.canonical_name
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    invalid_rows = [
        row
        for row in rows
        if not _is_valid_regional_title(row["promoted_title"] or row["wikipedia_title"])
    ]
    if limit is not None:
        invalid_rows = invalid_rows[:limit]
    return [
        _review_subject_dict(row, "invalid_region_title_review", row["region_id"])
        | {
            "suggested_title_replacements": [
                f"Music of {row['canonical_name']}",
                f"{row['canonical_name']} music",
            ]
        }
        for row in invalid_rows
    ]


def _review_subject_dict(row: Any, review_type: str, subject_key: str) -> dict[str, Any]:
    data = dict(row)
    data["review_type"] = review_type
    data["subject_key"] = subject_key
    return data


def _with_review_instructions(
    row: dict[str, Any],
    *,
    review_type: str,
    sample_size: int,
) -> dict[str, Any]:
    instructions_by_type = {
        "zero_child_source_review": (
            "Review whether this source/city region has real regional genre candidates. "
            "Use extract_candidates only for titles that are actual genres or regional genre pages; "
            "use keep when it is a valid organizational region with no owned genres; collapse/reject metadata-only nodes."
        ),
        "parentless_region_review": (
            "Anchor this promoted region to the most specific available parent. Prefer countries over continents; "
            "use multiple countries only for genuinely cross-border cultural/historical regions."
        ),
        "broad_region_genre_review": (
            "Broad regions may own unique broad genres. Keep broad ownership only when the genre is genuinely broad; "
            "otherwise move to specific regions, mark inherited from children, or demote as context only."
        ),
        "invalid_region_title_review": (
            "Promoted regional node titles must be Music of XXX or XXX music. Rename valid regional nodes; "
            "demote list/source-only pages and move useful children to the valid regional node."
        ),
    }
    return row | {
        "review_model": PRODUCTION_REVIEW_MODEL,
        "instructions": instructions_by_type[review_type],
        "max_candidate_titles": sample_size,
        "required_output_schema": {
            "decision": [
                "keep",
                "collapse",
                "anchor",
                "extract_candidates",
                "reject",
                "rename",
                "needs_human",
                "keep_broad",
                "move_to_specific_regions",
                "inherit_from_children",
                "context_only",
            ],
            "explanation": "Concise reason with page/source evidence.",
            "target_parents": "List of explicit region IDs/names when anchoring or moving.",
            "candidate_genres": "Title list when genre candidates are found.",
            "title_replacement": "Only for invalid promoted titles.",
            "confidence": ["high", "medium", "low"],
        },
    }


def _normalize_review_payload(
    payload: dict[str, Any],
    review_payload: dict[str, Any],
    batch_key: str | None,
    reviewer_model: str,
) -> dict[str, Any]:
    review_type = str(review_payload.get("review_type") or payload.get("review_type") or "")
    decision = str(review_payload.get("decision") or "")
    confidence = str(review_payload.get("confidence") or "")
    explanation = str(review_payload.get("explanation") or "").strip()
    if review_type not in PRODUCTION_REVIEW_TYPES:
        raise ValueError(f"invalid review_type {review_type!r}")
    if not _is_valid_review_decision(decision, review_type):
        raise ValueError(f"invalid decision {decision!r} for {review_type}")
    if confidence not in PRODUCTION_REVIEW_CONFIDENCE:
        raise ValueError(f"invalid confidence {confidence!r}")
    if not explanation:
        raise ValueError("explanation is required")
    subject_key = str(review_payload.get("subject_key") or payload.get("subject_key") or "")
    region_id = review_payload.get("region_id") or payload.get("region_id")
    rgr_id = (
        review_payload.get("region_genre_relationship_id")
        or payload.get("region_genre_relationship_id")
    )
    genre_id = review_payload.get("genre_id") or payload.get("genre_id")
    if not subject_key:
        subject_key = str(rgr_id or region_id or stable_key(json.dumps(payload, sort_keys=True)))
    target_parents = review_payload.get("target_parents") or []
    candidate_genres = review_payload.get("candidate_genres") or []
    if not isinstance(target_parents, list):
        raise ValueError("target_parents must be a list")
    if not isinstance(candidate_genres, list):
        raise ValueError("candidate_genres must be a list")
    decision_key = stable_key(
        "region-production-review-decision",
        review_type,
        subject_key,
        decision,
    )
    return {
        "decision_key": decision_key,
        "batch_key": review_payload.get("batch_key") or payload.get("batch_key") or batch_key,
        "review_type": review_type,
        "subject_key": subject_key,
        "region_id": region_id,
        "region_genre_relationship_id": rgr_id,
        "genre_id": genre_id,
        "decision": decision,
        "confidence": confidence,
        "explanation": explanation,
        "target_parents": target_parents,
        "candidate_genres": candidate_genres,
        "title_replacement": review_payload.get("title_replacement") or None,
        "reviewer_model": reviewer_model,
    }


async def _apply_zero_child_review(
    conn: Any,
    decision: dict[str, Any],
    stats: RegionProductionReviewApplyStats,
) -> bool:
    if decision["decision"] == "keep":
        await _mark_region_review_status(conn, decision, "reviewed_empty")
        stats.regions_marked += 1
        return True
    if decision["decision"] == "extract_candidates":
        candidate_titles = _json_list(decision["candidate_genres"])
        for title in candidate_titles:
            genre_id = await _find_genre_id(conn, str(title))
            if not genre_id:
                continue
            relation = await _relation_for_region_candidate(conn, decision["region_id"], str(title))
            result = await conn.execute(
                text("""
                    INSERT INTO wg_region_genre_relationships (
                        region_id,
                        genre_id,
                        relation,
                        source_type,
                        source_title,
                        evidence_text,
                        confidence,
                        status,
                        review_reason,
                        reviewer_model,
                        raw_payload
                    )
                    VALUES (
                        :region_id,
                        :genre_id,
                        :relation,
                        'gpt_review',
                        :source_title,
                        :evidence_text,
                        0.72,
                        'proposed',
                        :review_reason,
                        :reviewer_model,
                        jsonb_build_object(
                            'production_review_decision_key', CAST(:decision_key AS text),
                            'review_type', CAST(:review_type AS text)
                        )
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "region_id": decision["region_id"],
                    "genre_id": genre_id,
                    "relation": relation,
                    "source_title": PRODUCTION_REVIEW_SOURCE_TITLE,
                    "evidence_text": decision["explanation"],
                    "review_reason": "Staged from high-confidence zero-child production review.",
                    "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
                    "decision_key": decision["decision_key"],
                    "review_type": decision["review_type"],
                },
            )
            stats.candidate_edges_added += int(result.rowcount or 0)
        return True
    if decision["decision"] == "collapse":
        return await _collapse_review_region(conn, decision, stats, status="collapsed")
    if decision["decision"] == "reject":
        await _mark_region_review_status(conn, decision, "rejected")
        stats.regions_marked += 1
        return True
    return False


async def _apply_parentless_review(
    conn: Any,
    decision: dict[str, Any],
    stats: RegionProductionReviewApplyStats,
) -> bool:
    if decision["decision"] == "anchor":
        targets = await _resolve_target_regions(conn, _json_list(decision["target_parents"]))
        if not targets:
            return False
        for target in targets:
            result = await conn.execute(
                text("""
                    INSERT INTO wg_region_relationships (
                        from_region_id,
                        to_region_id,
                        relation,
                        source_type,
                        source_title,
                        evidence_text,
                        confidence,
                        status,
                        review_reason,
                        reviewer_model,
                        raw_payload
                    )
                    VALUES (
                        :from_region_id,
                        :to_region_id,
                        :relation,
                        'gpt_review',
                        :source_title,
                        :evidence_text,
                        0.9,
                        'accepted',
                        :review_reason,
                        :reviewer_model,
                        jsonb_build_object(
                            'production_review_decision_key', CAST(:decision_key AS text),
                            'target_parent_raw', CAST(:target_parent_raw AS jsonb)
                        )
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "from_region_id": decision["region_id"],
                    "to_region_id": target["id"],
                    "relation": target.get("relation") or "part_of",
                    "source_title": PRODUCTION_REVIEW_SOURCE_TITLE,
                    "evidence_text": decision["explanation"],
                    "review_reason": "Anchored by high-confidence region production review.",
                    "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
                    "decision_key": decision["decision_key"],
                    "target_parent_raw": json.dumps(target.get("raw") or {}, sort_keys=True),
                },
            )
            stats.anchors_added += int(result.rowcount or 0)
        return True
    if decision["decision"] == "keep":
        await _mark_region_review_status(conn, decision, "approved_superregion")
        stats.regions_marked += 1
        return True
    if decision["decision"] == "collapse":
        return await _collapse_review_region(conn, decision, stats, status="collapsed")
    if decision["decision"] == "reject":
        await _mark_region_review_status(conn, decision, "rejected")
        stats.regions_marked += 1
        return True
    return False


async def _apply_broad_region_genre_review(
    conn: Any,
    decision: dict[str, Any],
    stats: RegionProductionReviewApplyStats,
) -> bool:
    if decision["decision"] == "keep_broad":
        await conn.execute(
            text("""
                UPDATE wg_region_genre_relationships
                SET raw_payload = raw_payload || jsonb_build_object(
                        'broad_region_review',
                        jsonb_build_object(
                            'decision_key', CAST(:decision_key AS text),
                            'decision', CAST(:decision AS text),
                            'explanation', CAST(:explanation AS text)
                        )
                    ),
                    updated_at = now()
                WHERE id = :relationship_id
            """),
            {
                "relationship_id": decision["region_genre_relationship_id"],
                "decision_key": decision["decision_key"],
                "decision": decision["decision"],
                "explanation": decision["explanation"],
            },
        )
        return True
    if decision["decision"] == "move_to_specific_regions":
        targets = await _resolve_target_regions(conn, _json_list(decision["target_parents"]))
        if not targets:
            return False
        source = await _load_region_genre_relationship(conn, decision["region_genre_relationship_id"])
        if not source:
            return False
        for target in targets:
            result = await conn.execute(
                text("""
                    INSERT INTO wg_region_genre_relationships (
                        region_id,
                        genre_id,
                        relation,
                        source_type,
                        source_title,
                        evidence_text,
                        confidence,
                        status,
                        review_reason,
                        reviewer_model,
                        raw_payload
                    )
                    VALUES (
                        :region_id,
                        :genre_id,
                        :relation,
                        'gpt_review',
                        :source_title,
                        :evidence_text,
                        :confidence,
                        'accepted',
                        :review_reason,
                        :reviewer_model,
                        jsonb_build_object(
                            'moved_from_region_id', CAST(:moved_from_region_id AS text),
                            'production_review_decision_key', CAST(:decision_key AS text)
                        )
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "region_id": target["id"],
                    "genre_id": source["genre_id"],
                    "relation": source["relation"],
                    "source_title": PRODUCTION_REVIEW_SOURCE_TITLE,
                    "evidence_text": decision["explanation"],
                    "confidence": source["confidence"],
                    "review_reason": "Moved from broad region by high-confidence production review.",
                    "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
                    "moved_from_region_id": source["region_id"],
                    "decision_key": decision["decision_key"],
                },
            )
            stats.candidate_edges_added += int(result.rowcount or 0)
        await _demote_region_genre_relationship(conn, decision, "regional_style_mention")
        stats.relationships_demoted += 1
        return True
    if decision["decision"] in {"inherit_from_children", "context_only"}:
        await _demote_region_genre_relationship(conn, decision, "regional_style_mention")
        stats.relationships_demoted += 1
        return True
    return False


async def _apply_invalid_title_review(
    conn: Any,
    decision: dict[str, Any],
    stats: RegionProductionReviewApplyStats,
) -> bool:
    if decision["decision"] == "rename":
        replacement = decision.get("title_replacement")
        if not _is_valid_regional_title(replacement):
            return False
        promoted = await conn.execute(
            text("""
                SELECT genre_id
                FROM wg_region_promoted_genres
                WHERE region_id = :region_id
            """),
            {"region_id": decision["region_id"]},
        )
        promoted_row = promoted.mappings().first()
        promoted_genre_id = promoted_row["genre_id"] if promoted_row else None
        conflict_id = await conn.scalar(
            text("""
                SELECT id
                FROM wg_genres
                WHERE lower(wikipedia_title) = lower(:title)
                  AND (CAST(:genre_id AS text) IS NULL OR id <> CAST(:genre_id AS text))
                LIMIT 1
            """),
            {"title": replacement, "genre_id": promoted_genre_id},
        )
        if conflict_id:
            conflict_promoted_region = await conn.scalar(
                text("""
                    SELECT region_id
                    FROM wg_region_promoted_genres
                    WHERE genre_id = :genre_id
                      AND region_id <> :region_id
                    LIMIT 1
                """),
                {"genre_id": str(conflict_id), "region_id": decision["region_id"]},
            )
            if conflict_promoted_region:
                return False
        await conn.execute(
            text("""
                UPDATE wg_regions
                SET wikipedia_title = :title,
                    display_title = :title,
                    raw_payload = raw_payload || jsonb_build_object(
                        'region_production_review',
                        jsonb_build_object(
                            'status', 'renamed',
                            'decision_key', CAST(:decision_key AS text),
                            'explanation', CAST(:explanation AS text)
                        )
                    ),
                    updated_at = now()
                WHERE id = :region_id
            """),
            {
                "title": replacement,
                "decision_key": decision["decision_key"],
                "explanation": decision["explanation"],
                "region_id": decision["region_id"],
            },
        )
        await conn.execute(
            text("""
                UPDATE wg_region_promoted_genres
                SET genre_id = coalesce(CAST(:replacement_genre_id AS text), genre_id),
                    wikipedia_title = :title,
                    promotion_rule = 'reviewed_region_title'
                WHERE region_id = :region_id
            """),
            {
                "title": replacement,
                "region_id": decision["region_id"],
                "replacement_genre_id": str(conflict_id) if conflict_id else None,
            },
        )
        if promoted_genre_id and not conflict_id:
            await conn.execute(
                text("""
                    UPDATE wg_genres
                    SET wikipedia_title = :title,
                        wikipedia_url = 'https://en.wikipedia.org/wiki/' || replace(:title, ' ', '_'),
                        non_genre_review_note = coalesce(non_genre_review_note, '') ||
                            ' Region production review renamed invalid regional title.'
                    WHERE id = :genre_id
                """),
                {"title": replacement, "genre_id": promoted_genre_id},
            )
        stats.regions_renamed += 1
        return True
    if decision["decision"] == "collapse":
        return await _collapse_review_region(conn, decision, stats, status="demoted_source")
    if decision["decision"] == "reject":
        current_title = await conn.scalar(
            text("""
                SELECT coalesce(promoted.wikipedia_title, region.wikipedia_title)
                FROM wg_regions region
                LEFT JOIN wg_region_promoted_genres promoted
                  ON promoted.region_id = region.id
                WHERE region.id = :region_id
            """),
            {"region_id": decision["region_id"]},
        )
        await _mark_region_review_status(
            conn,
            decision,
            "reviewed_empty" if _is_valid_regional_title(str(current_title or "")) else "demoted_source",
        )
        stats.regions_marked += 1
        return True
    return False


async def _mark_region_review_status(conn: Any, decision: dict[str, Any], status: str) -> None:
    await conn.execute(
        text("""
            UPDATE wg_regions
            SET raw_payload = raw_payload || jsonb_build_object(
                    'region_production_review',
                    jsonb_build_object(
                        'status', CAST(:status AS text),
                        'decision_key', CAST(:decision_key AS text),
                        'review_type', CAST(:review_type AS text),
                        'decision', CAST(:decision AS text),
                        'explanation', CAST(:explanation AS text),
                        'reviewer_model', CAST(:reviewer_model AS text)
                    )
                ),
                updated_at = now()
            WHERE id = :region_id
              AND NOT (
                :status = 'reviewed_empty'
                AND coalesce(raw_payload #>> '{region_production_review,status}', '') IN (
                    'collapsed',
                    'rejected',
                    'demoted_source'
                )
              )
        """),
        {
            "status": status,
            "decision_key": decision["decision_key"],
            "review_type": decision["review_type"],
            "decision": decision["decision"],
            "explanation": decision["explanation"],
            "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
            "region_id": decision["region_id"],
        },
    )


async def _collapse_review_region(
    conn: Any,
    decision: dict[str, Any],
    stats: RegionProductionReviewApplyStats,
    *,
    status: str,
) -> bool:
    targets = await _resolve_target_regions(conn, _json_list(decision["target_parents"]))
    if not targets:
        await _mark_region_review_status(conn, decision, status)
        stats.regions_marked += 1
        return True
    target_id = targets[0]["id"]
    await conn.execute(
        text("""
            INSERT INTO wg_region_sources (
                region_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                extractor_model,
                confidence,
                raw_payload
            )
            SELECT
                :target_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                extractor_model,
                confidence,
                raw_payload || jsonb_build_object(
                    'collapsed_from_region_id', CAST(:region_id AS text),
                    'production_review_decision_key', CAST(:decision_key AS text)
                )
            FROM wg_region_sources
            WHERE region_id = :region_id
            ON CONFLICT DO NOTHING
        """),
        {
            "target_id": target_id,
            "region_id": decision["region_id"],
            "decision_key": decision["decision_key"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO wg_region_genre_relationships (
                region_id,
                genre_id,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                review_reason,
                reviewer_model,
                raw_payload
            )
            SELECT
                :target_id,
                genre_id,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                coalesce(review_reason, '') || ' Region production review: copied from collapsed region.',
                :reviewer_model,
                raw_payload || jsonb_build_object(
                    'collapsed_from_region_id', CAST(:region_id AS text),
                    'production_review_decision_key', CAST(:decision_key AS text)
                )
            FROM wg_region_genre_relationships
            WHERE region_id = :region_id
            ON CONFLICT DO NOTHING
        """),
        {
            "target_id": target_id,
            "region_id": decision["region_id"],
            "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
            "decision_key": decision["decision_key"],
        },
    )
    await conn.execute(
        text("""
            INSERT INTO wg_region_relationships (
                from_region_id,
                to_region_id,
                relation,
                source_type,
                source_title,
                evidence_text,
                confidence,
                status,
                review_reason,
                reviewer_model,
                raw_payload
            )
            SELECT
                child.id,
                :target_id,
                rel.relation,
                'gpt_review',
                :source_title,
                :evidence_text,
                greatest(rel.confidence, 0.8),
                'accepted',
                'Region production review: moved child to collapsed region parent.',
                :reviewer_model,
                jsonb_build_object(
                    'collapsed_parent_region_id', CAST(:region_id AS text),
                    'production_review_decision_key', CAST(:decision_key AS text)
                )
            FROM wg_region_relationships rel
            JOIN wg_regions child ON child.id = rel.from_region_id
            WHERE rel.to_region_id = :region_id
              AND rel.status = 'accepted'
              AND child.id <> :target_id
            ON CONFLICT DO NOTHING
        """),
        {
            "target_id": target_id,
            "region_id": decision["region_id"],
            "source_title": PRODUCTION_REVIEW_SOURCE_TITLE,
            "evidence_text": decision["explanation"],
            "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
            "decision_key": decision["decision_key"],
        },
    )
    await _mark_region_review_status(conn, decision, status)
    stats.regions_marked += 1
    return True


async def _resolve_target_regions(conn: Any, targets: list[Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for target in targets:
        raw = target
        relation = None
        if isinstance(target, dict):
            relation = target.get("relation")
            value = target.get("region_id") or target.get("id") or target.get("name") or target.get("title")
        else:
            value = target
        if not value:
            continue
        row = await _resolve_one_region_target(conn, str(value))
        if row:
            resolved.append(dict(row) | {"relation": relation or "part_of", "raw": raw})
    return sorted(
        resolved,
        key=lambda item: _parent_preference_rank(kind=item.get("kind"), name=item.get("canonical_name")),
    )


async def _resolve_one_region_target(conn: Any, value: str) -> dict[str, Any] | None:
    candidates = [value]
    normalized = _normalize(value)
    target_aliases = {
        "andean region": "Andes",
        "nordic countries": "Nordic",
    }
    if normalized in target_aliases:
        candidates.append(target_aliases[normalized])
    for suffix in (" countries", " region"):
        if normalized.endswith(suffix):
            candidates.append(value[: -len(suffix)].strip())

    for candidate in candidates:
        if not candidate:
            continue
        row = (
            (
                await conn.execute(
                    text("""
                        SELECT id, canonical_name, kind
                        FROM wg_regions
                        WHERE id = :value
                           OR lower(canonical_name) = lower(:value)
                           OR lower(coalesce(display_title, '')) = lower(:value)
                           OR lower(coalesce(wikipedia_title, '')) = lower(:value)
                        ORDER BY
                            CASE WHEN id = :value THEN 0 ELSE 1 END,
                            canonical_name
                        LIMIT 1
                    """),
                    {"value": candidate},
                )
            )
            .mappings()
            .first()
        )
        if row:
            return dict(row)
    return None


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


async def _find_genre_id(conn: Any, title: str) -> str | None:
    value = await conn.scalar(
        text("""
            SELECT id
            FROM wg_genres
            WHERE lower(wikipedia_title) = lower(:title)
              AND deleted_at IS NULL
              AND is_non_genre = false
            LIMIT 1
        """),
        {"title": title},
    )
    return str(value) if value else None


async def _relation_for_region_candidate(conn: Any, region_id: str, title: str) -> str:
    kind = await conn.scalar(text("SELECT kind FROM wg_regions WHERE id = :id"), {"id": region_id})
    normalized_title = _normalize(title)
    if "indigenous" in normalized_title:
        return "indigenous_region"
    if "historical" in normalized_title or "ancient" in normalized_title:
        return "historical_region"
    if "folk" in normalized_title or "traditional" in normalized_title:
        return "traditional_region"
    if kind == "city":
        return "local_scene"
    return "regional_scene"


async def _load_region_genre_relationship(conn: Any, relationship_id: int | None) -> dict[str, Any] | None:
    if relationship_id is None:
        return None
    row = (
        (
            await conn.execute(
                text("""
                    SELECT *
                    FROM wg_region_genre_relationships
                    WHERE id = :id
                """),
                {"id": relationship_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def _demote_region_genre_relationship(
    conn: Any,
    decision: dict[str, Any],
    relation: str,
) -> None:
    await conn.execute(
        text("""
            UPDATE wg_region_genre_relationships
            SET relation = :relation,
                review_reason = coalesce(review_reason, '') ||
                    ' Region production review demoted broad ownership: ' || :explanation,
                reviewer_model = :reviewer_model,
                raw_payload = raw_payload || jsonb_build_object(
                    'broad_region_review',
                    jsonb_build_object(
                        'decision_key', CAST(:decision_key AS text),
                        'decision', CAST(:decision AS text),
                        'explanation', CAST(:explanation AS text)
                    )
                ),
                updated_at = now()
            WHERE id = :relationship_id
        """),
        {
            "relationship_id": decision["region_genre_relationship_id"],
            "relation": relation,
            "explanation": decision["explanation"],
            "reviewer_model": decision["reviewer_model"] or PRODUCTION_REVIEW_MODEL,
            "decision_key": decision["decision_key"],
            "decision": decision["decision"],
        },
    )


async def _canonicalize_proxy_genre_row(conn: Any, candidate: AliasProxyCandidate) -> str | None:
    if not candidate.promoted_genre_id:
        return None
    desired_title = candidate.old_wikipedia_title
    if not desired_title or not _is_style_proxy_title(desired_title, candidate.old_name):
        return candidate.promoted_genre_id

    existing_id = await conn.scalar(
        text("""
            SELECT id
            FROM wg_genres
            WHERE lower(wikipedia_title) = lower(:desired_title)
            LIMIT 1
        """),
        {"desired_title": desired_title},
    )
    if existing_id and existing_id != candidate.promoted_genre_id:
        return str(existing_id)

    await conn.execute(
        text("""
            UPDATE wg_genres
            SET wikipedia_title = :desired_title,
                wikipedia_url = 'https://en.wikipedia.org/wiki/' || replace(:desired_title, ' ', '_'),
                summary = CASE
                    WHEN summary = 'Reviewed regional music node promoted into the genre graph.'
                    THEN 'Reviewed regional style page canonicalized under its region.'
                    ELSE summary
                END,
                non_genre_review_note = coalesce(non_genre_review_note, '') ||
                    ' Deterministic cleanup: repaired malformed proxy title.'
            WHERE id = :genre_id
              AND wikipedia_title = 'Music of ' || :old_name
        """),
        {
            "genre_id": candidate.promoted_genre_id,
            "desired_title": desired_title,
            "old_name": candidate.old_name,
        },
    )
    return candidate.promoted_genre_id


async def _copy_region_sources(conn: Any, candidate: AliasProxyCandidate) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO wg_region_sources (
                region_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                extractor_model,
                confidence,
                raw_payload
            )
            SELECT
                :target_region_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                extractor_model,
                confidence,
                raw_payload || jsonb_build_object(
                    'merged_from_region_id', CAST(:old_region_id AS text),
                    'cleanup_model', CAST(:reviewer_model AS text)
                )
            FROM wg_region_sources
            WHERE region_id = :old_region_id
            ON CONFLICT DO NOTHING
        """),
        {
            "old_region_id": candidate.old_region_id,
            "target_region_id": candidate.target_region_id,
            "reviewer_model": CLEANUP_MODEL,
        },
    )
    return int(result.rowcount or 0)


async def _copy_region_music_pages(
    conn: Any,
    candidate: AliasProxyCandidate,
    *,
    canonical_genre_id: str | None,
) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO wg_region_music_pages (
                region_id,
                genre_id,
                role,
                source_id,
                source_type,
                source_url,
                source_title,
                evidence_text,
                confidence,
                raw_payload
            )
            SELECT
                :target_region_id,
                CASE
                    WHEN genre_id = CAST(:old_promoted_genre_id AS text)
                     AND CAST(:canonical_genre_id AS text) IS NOT NULL
                    THEN CAST(:canonical_genre_id AS text)
                    ELSE genre_id
                END,
                role,
                source_id,
                source_type,
                source_url,
                source_title,
                evidence_text,
                confidence,
                raw_payload || jsonb_build_object(
                    'merged_from_region_id', CAST(:old_region_id AS text),
                    'cleanup_model', CAST(:reviewer_model AS text)
                )
            FROM wg_region_music_pages
            WHERE region_id = :old_region_id
            ON CONFLICT DO NOTHING
        """),
        {
            "old_region_id": candidate.old_region_id,
            "target_region_id": candidate.target_region_id,
            "old_promoted_genre_id": candidate.promoted_genre_id,
            "canonical_genre_id": canonical_genre_id,
            "reviewer_model": CLEANUP_MODEL,
        },
    )
    return int(result.rowcount or 0)


async def _copy_region_relationships(conn: Any, candidate: AliasProxyCandidate) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO wg_region_relationships (
                from_region_id,
                to_region_id,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                review_reason,
                reviewer_model,
                raw_payload
            )
            SELECT
                CASE WHEN from_region_id = :old_region_id THEN :target_region_id ELSE from_region_id END,
                CASE WHEN to_region_id = :old_region_id THEN :target_region_id ELSE to_region_id END,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                coalesce(review_reason, '') ||
                    ' Deterministic cleanup: copied from merged demonym/style proxy.',
                :reviewer_model,
                raw_payload || jsonb_build_object(
                    'merged_from_region_id', CAST(:old_region_id AS text),
                    'cleanup_model', CAST(:reviewer_model AS text)
                )
            FROM wg_region_relationships
            WHERE (from_region_id = :old_region_id OR to_region_id = :old_region_id)
              AND (
                CASE WHEN from_region_id = :old_region_id THEN :target_region_id ELSE from_region_id END
              ) <> (
                CASE WHEN to_region_id = :old_region_id THEN :target_region_id ELSE to_region_id END
              )
            ON CONFLICT DO NOTHING
        """),
        {
            "old_region_id": candidate.old_region_id,
            "target_region_id": candidate.target_region_id,
            "reviewer_model": CLEANUP_MODEL,
        },
    )
    return int(result.rowcount or 0)


async def _copy_region_genre_relationships(
    conn: Any,
    candidate: AliasProxyCandidate,
    *,
    canonical_genre_id: str | None,
) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO wg_region_genre_relationships (
                region_id,
                genre_id,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                review_reason,
                reviewer_model,
                raw_payload
            )
            SELECT
                :target_region_id,
                CASE
                    WHEN genre_id = CAST(:old_promoted_genre_id AS text)
                     AND CAST(:canonical_genre_id AS text) IS NOT NULL
                    THEN CAST(:canonical_genre_id AS text)
                    ELSE genre_id
                END,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                coalesce(review_reason, '') ||
                    ' Deterministic cleanup: copied from merged demonym/style proxy.',
                :reviewer_model,
                raw_payload || jsonb_build_object(
                    'merged_from_region_id', CAST(:old_region_id AS text),
                    'cleanup_model', CAST(:reviewer_model AS text)
                )
            FROM wg_region_genre_relationships
            WHERE region_id = :old_region_id
            ON CONFLICT DO NOTHING
        """),
        {
            "old_region_id": candidate.old_region_id,
            "target_region_id": candidate.target_region_id,
            "old_promoted_genre_id": candidate.promoted_genre_id,
            "canonical_genre_id": canonical_genre_id,
            "reviewer_model": CLEANUP_MODEL,
        },
    )
    return int(result.rowcount or 0)


async def _delete_unreferenced_proxy_genre(conn: Any, candidate: AliasProxyCandidate) -> None:
    if not candidate.promoted_genre_id:
        return
    await conn.execute(
        text("""
            DELETE FROM wg_genres genre
            WHERE genre.id = :genre_id
              AND genre.wikipedia_title = 'Music of ' || :old_name
              AND NOT EXISTS (
                SELECT 1 FROM wg_region_genre_relationships rel WHERE rel.genre_id = genre.id
              )
              AND NOT EXISTS (
                SELECT 1 FROM wg_region_music_pages page WHERE page.genre_id = genre.id
              )
        """),
        {"genre_id": candidate.promoted_genre_id, "old_name": candidate.old_name},
    )


def _stats_to_dict(stats: RegionProductionAuditStats) -> dict[str, Any]:
    return {
        "production_ready": stats.production_ready,
        "regions": stats.regions,
        "promoted_regions": stats.promoted_regions,
        "region_relationships": stats.region_relationships,
        "region_genre_relationships": stats.region_genre_relationships,
        "accepted_region_relationships": stats.accepted_region_relationships,
        "accepted_graph_region_genre_relationships": stats.accepted_graph_region_genre_relationships,
        "candidate_rows": stats.candidate_rows,
        "discovery_sources": stats.discovery_sources,
        "zero_child_promoted_regions": stats.zero_child_promoted_regions,
        "parentless_accepted_regions": stats.parentless_accepted_regions,
        "malformed_region_candidates": stats.malformed_region_candidates,
        "alias_proxy_candidates": stats.alias_proxy_candidates,
        "invalid_region_titles": stats.invalid_region_titles,
        "duplicate_region_genre_pairs": stats.duplicate_region_genre_pairs,
        "broad_region_genre_edges": stats.broad_region_genre_edges,
        "graph_affecting_needs_review": stats.graph_affecting_needs_review,
        "pending_candidate_rows": stats.pending_candidate_rows,
        "samples": stats.samples,
        "breakdowns": stats.breakdowns,
    }


def _render_markdown_report(stats: RegionProductionAuditStats) -> str:
    lines = [
        "# Region Production Audit",
        "",
        f"- Production ready: `{stats.production_ready}`",
        f"- Regions: `{stats.regions}`",
        f"- Promoted regions: `{stats.promoted_regions}`",
        f"- Region relationships: `{stats.region_relationships}`",
        f"- Region-genre relationships: `{stats.region_genre_relationships}`",
        f"- Accepted graph region-genre relationships: `{stats.accepted_graph_region_genre_relationships}`",
        f"- Zero-child promoted regions: `{stats.zero_child_promoted_regions}`",
        f"- Parentless promoted regions: `{stats.parentless_accepted_regions}`",
        f"- Alias/style proxy cleanup candidates: `{stats.alias_proxy_candidates}`",
        f"- Invalid promoted region titles: `{stats.invalid_region_titles}`",
        f"- Duplicate region-genre pairs: `{stats.duplicate_region_genre_pairs}`",
        f"- Broad region-genre edges: `{stats.broad_region_genre_edges}`",
        f"- Graph-affecting needs-review rows: `{stats.graph_affecting_needs_review}`",
        f"- Pending candidate rows: `{stats.pending_candidate_rows}`",
        "",
    ]

    for key, rows in stats.breakdowns.items():
        lines.extend([f"## {key}", ""])
        lines.extend(_markdown_table(rows))
        lines.append("")

    for key, rows in stats.samples.items():
        lines.extend([f"## Sample: {key}", ""])
        lines.extend(_markdown_table(rows))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_None._"]
    columns = list(rows[0].keys())
    output = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        output.append(
            "| "
            + " | ".join(_markdown_cell(row.get(column)) for column in columns)
            + " |"
        )
    return output


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value.replace("|", "\\|")
