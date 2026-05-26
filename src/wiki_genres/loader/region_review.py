"""Region-graph duplicate detection and GPT review batch export."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)


@dataclass
class RegionMergeCandidateStats:
    rows_seen: int = 0
    rows_upserted: int = 0
    deleted_existing: int = 0
    sample: list[str] = field(default_factory=list)


@dataclass
class RegionTreeReviewBatchStats:
    batches_exported: int = 0
    regions_exported: int = 0
    region_edges_exported: int = 0
    genre_edges_exported: int = 0
    output_dir: Path | None = None
    sample: list[str] = field(default_factory=list)


@dataclass
class RegionTreeReviewFindingImportStats:
    rows_seen: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)


def stable_key(*parts: str) -> str:
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:24]


def normalize_region_label(label: str) -> str:
    clean = label.lower()
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = clean.replace("&", " and ")
    clean = re.sub(
        r"\b(music|musical|of|the|region|regions|regional|category|list|genres?|styles?)\b",
        " ",
        clean,
    )
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return " ".join(clean.split())


async def index_region_merge_candidates(
    *,
    reset: bool = False,
    limit: int = 5000,
    sample_size: int = 25,
) -> RegionMergeCandidateStats:
    """Stage likely duplicate region nodes without mutating the region graph."""
    await apply_migrations()
    stats = RegionMergeCandidateStats()
    engine = get_engine()

    async with engine.begin() as conn:
        if reset:
            deleted = await conn.execute(text("DELETE FROM wg_region_merge_candidates"))
            stats.deleted_existing = deleted.rowcount or 0

        rows = (
            (
                await conn.execute(
                    text("""
                        WITH active_regions AS (
                            SELECT
                                r.id,
                                r.canonical_name,
                                r.kind,
                                r.display_title,
                                r.wikipedia_title,
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            lower(
                                                coalesce(
                                                    nullif(r.canonical_name, ''),
                                                    nullif(r.display_title, ''),
                                                    r.wikipedia_title,
                                                    r.id
                                                )
                                            ),
                                            '\\([^)]*\\)',
                                            ' ',
                                            'g'
                                        ),
                                        '\\m(music|musical|of|the|region|regions|regional|category|list|genres?|styles?)\\M',
                                        ' ',
                                        'g'
                                    ),
                                    '[^a-z0-9]+',
                                    ' ',
                                    'g'
                                ) AS normalized_name
                            FROM wg_regions r
                        ),
                        name_pairs AS (
                            SELECT
                                LEAST(a.id, b.id) AS left_region_id,
                                GREATEST(a.id, b.id) AS right_region_id,
                                CASE WHEN a.id < b.id THEN a.canonical_name ELSE b.canonical_name END AS left_name,
                                CASE WHEN a.id < b.id THEN b.canonical_name ELSE a.canonical_name END AS right_name,
                                similarity(a.normalized_name, b.normalized_name) AS name_similarity,
                                a.normalized_name = b.normalized_name AS normalized_match,
                                a.kind = b.kind AS same_kind
                            FROM active_regions a
                            JOIN active_regions b ON a.id < b.id
                            WHERE (
                                a.normalized_name = b.normalized_name
                                OR similarity(a.normalized_name, b.normalized_name) >= 0.82
                            )
                        ),
                        source_pairs AS (
                            SELECT
                                LEAST(a.region_id, b.region_id) AS left_region_id,
                                GREATEST(a.region_id, b.region_id) AS right_region_id,
                                count(*) AS source_overlap_count
                            FROM wg_region_sources a
                            JOIN wg_region_sources b
                              ON a.region_id < b.region_id
                             AND (
                                  nullif(lower(a.source_url), '') = nullif(lower(b.source_url), '')
                                  OR nullif(lower(a.source_title), '') = nullif(lower(b.source_title), '')
                             )
                            WHERE a.region_id IS NOT NULL
                              AND b.region_id IS NOT NULL
                            GROUP BY 1, 2
                        ),
                        parent_pairs AS (
                            SELECT
                                LEAST(r1.from_region_id, r2.from_region_id) AS left_region_id,
                                GREATEST(r1.from_region_id, r2.from_region_id) AS right_region_id,
                                count(DISTINCT r1.to_region_id) AS shared_parent_count
                            FROM wg_region_relationships r1
                            JOIN wg_region_relationships r2
                              ON r1.to_region_id = r2.to_region_id
                             AND r1.from_region_id < r2.from_region_id
                            WHERE r1.status = 'accepted'
                              AND r2.status = 'accepted'
                            GROUP BY 1, 2
                        ),
                        child_pairs AS (
                            SELECT
                                LEAST(r1.to_region_id, r2.to_region_id) AS left_region_id,
                                GREATEST(r1.to_region_id, r2.to_region_id) AS right_region_id,
                                count(DISTINCT r1.from_region_id) AS shared_child_count
                            FROM wg_region_relationships r1
                            JOIN wg_region_relationships r2
                              ON r1.from_region_id = r2.from_region_id
                             AND r1.to_region_id < r2.to_region_id
                            WHERE r1.status = 'accepted'
                              AND r2.status = 'accepted'
                            GROUP BY 1, 2
                        ),
                        genre_pairs AS (
                            SELECT
                                LEAST(r1.region_id, r2.region_id) AS left_region_id,
                                GREATEST(r1.region_id, r2.region_id) AS right_region_id,
                                count(DISTINCT r1.genre_id) AS shared_genre_count
                            FROM wg_region_genre_relationships r1
                            JOIN wg_region_genre_relationships r2
                              ON r1.genre_id = r2.genre_id
                             AND r1.region_id < r2.region_id
                            WHERE r1.status = 'accepted'
                              AND r2.status = 'accepted'
                            GROUP BY 1, 2
                        ),
                        all_pairs AS (
                            SELECT left_region_id, right_region_id FROM name_pairs
                        )
                        SELECT
                            p.left_region_id,
                            p.right_region_id,
                            left_r.canonical_name AS left_name,
                            right_r.canonical_name AS right_name,
                            coalesce(np.name_similarity, similarity(left_r.normalized_name, right_r.normalized_name)) AS name_similarity,
                            coalesce(np.normalized_match, left_r.normalized_name = right_r.normalized_name) AS normalized_match,
                            coalesce(np.same_kind, left_r.kind = right_r.kind) AS same_kind,
                            coalesce(sp.source_overlap_count, 0) AS source_overlap_count,
                            coalesce(pp.shared_parent_count, 0) AS shared_parent_count,
                            coalesce(cp.shared_child_count, 0) AS shared_child_count,
                            coalesce(gp.shared_genre_count, 0) AS shared_genre_count,
                            LEAST(
                                1.0,
                                (
                                    coalesce(np.name_similarity, similarity(left_r.normalized_name, right_r.normalized_name)) * 0.50
                                    + CASE WHEN coalesce(np.normalized_match, left_r.normalized_name = right_r.normalized_name) THEN 0.24 ELSE 0 END
                                    + CASE WHEN coalesce(np.same_kind, left_r.kind = right_r.kind) THEN 0.05 ELSE 0 END
                                    + LEAST(coalesce(sp.source_overlap_count, 0), 3) * 0.06
                                    + LEAST(coalesce(pp.shared_parent_count, 0), 4) * 0.025
                                    + LEAST(coalesce(cp.shared_child_count, 0), 4) * 0.02
                                    + LEAST(coalesce(gp.shared_genre_count, 0), 8) * 0.015
                                )
                            ) AS score
                        FROM all_pairs p
                        JOIN active_regions left_r ON left_r.id = p.left_region_id
                        JOIN active_regions right_r ON right_r.id = p.right_region_id
                        LEFT JOIN name_pairs np
                          ON np.left_region_id = p.left_region_id
                         AND np.right_region_id = p.right_region_id
                        LEFT JOIN source_pairs sp
                          ON sp.left_region_id = p.left_region_id
                         AND sp.right_region_id = p.right_region_id
                        LEFT JOIN parent_pairs pp
                          ON pp.left_region_id = p.left_region_id
                         AND pp.right_region_id = p.right_region_id
                        LEFT JOIN child_pairs cp
                          ON cp.left_region_id = p.left_region_id
                         AND cp.right_region_id = p.right_region_id
                        LEFT JOIN genre_pairs gp
                          ON gp.left_region_id = p.left_region_id
                         AND gp.right_region_id = p.right_region_id
                        WHERE (
                            coalesce(np.normalized_match, left_r.normalized_name = right_r.normalized_name)
                            OR coalesce(np.name_similarity, similarity(left_r.normalized_name, right_r.normalized_name)) >= 0.86
                        )
                        ORDER BY score DESC, name_similarity DESC, left_name, right_name
                        LIMIT :limit
                    """),
                    {"limit": limit},
                )
            )
            .mappings()
            .fetchall()
        )

        stats.rows_seen = len(rows)
        for row in rows:
            row_dict = dict(row)
            key = stable_key(
                "region-merge",
                row_dict["left_region_id"],
                row_dict["right_region_id"],
            )
            status = "needs_review"
            review_reason = "Region similarity pass candidate."
            scoped_name_pattern = re.compile(
                r"\((city|state|province|u\.s\. state)\)",
                re.IGNORECASE,
            )
            if (
                not row_dict["same_kind"]
                and (
                    scoped_name_pattern.search(row_dict["left_name"])
                    or scoped_name_pattern.search(row_dict["right_name"])
                )
            ):
                status = "do_not_merge"
                review_reason = (
                    "Deterministic review: distinct city, province, state, or country/state scope."
                )
            await conn.execute(
                text("""
                    INSERT INTO wg_region_merge_candidates (
                        candidate_key,
                        left_region_id,
                        right_region_id,
                        left_name,
                        right_name,
                        score,
                        name_similarity,
                        normalized_match,
                        same_kind,
                        source_overlap_count,
                        shared_parent_count,
                        shared_child_count,
                        shared_genre_count,
                        evidence,
                        status,
                        review_reason,
                        reviewer_model,
                        updated_at
                    )
                    VALUES (
                        :candidate_key,
                        :left_region_id,
                        :right_region_id,
                        :left_name,
                        :right_name,
                        :score,
                        :name_similarity,
                        :normalized_match,
                        :same_kind,
                        :source_overlap_count,
                        :shared_parent_count,
                        :shared_child_count,
                        :shared_genre_count,
                        :evidence,
                        :status,
                        :review_reason,
                        'deterministic-region-similarity-v1',
                        now()
                    )
                    ON CONFLICT (candidate_key) DO UPDATE
                    SET score = excluded.score,
                        name_similarity = excluded.name_similarity,
                        normalized_match = excluded.normalized_match,
                        same_kind = excluded.same_kind,
                        source_overlap_count = excluded.source_overlap_count,
                        shared_parent_count = excluded.shared_parent_count,
                        shared_child_count = excluded.shared_child_count,
                        shared_genre_count = excluded.shared_genre_count,
                        evidence = excluded.evidence,
                        status = CASE
                            WHEN wg_region_merge_candidates.status IN (
                                'merge',
                                'do_not_merge',
                                'rejected'
                            )
                            THEN wg_region_merge_candidates.status
                            ELSE excluded.status
                        END,
                        review_reason = CASE
                            WHEN wg_region_merge_candidates.status IN (
                                'merge',
                                'do_not_merge',
                                'rejected'
                            )
                            THEN wg_region_merge_candidates.review_reason
                            ELSE excluded.review_reason
                        END,
                        reviewer_model = excluded.reviewer_model,
                        updated_at = now()
                """),
                {
                    **row_dict,
                    "candidate_key": key,
                    "evidence": json.dumps(
                        {
                            "normalized_left": normalize_region_label(row_dict["left_name"]),
                            "normalized_right": normalize_region_label(row_dict["right_name"]),
                            "signals": {
                                "name_similarity": row_dict["name_similarity"],
                                "normalized_match": row_dict["normalized_match"],
                                "same_kind": row_dict["same_kind"],
                                "source_overlap_count": row_dict["source_overlap_count"],
                                "shared_parent_count": row_dict["shared_parent_count"],
                                "shared_child_count": row_dict["shared_child_count"],
                                "shared_genre_count": row_dict["shared_genre_count"],
                            },
                        }
                    ),
                    "status": status,
                    "review_reason": review_reason,
                },
            )
            stats.rows_upserted += 1
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{row_dict['left_name']} <> {row_dict['right_name']} score={row_dict['score']:.2f}"
                )

    logger.info(
        "region_merge_candidates_indexed",
        rows_seen=stats.rows_seen,
        rows_upserted=stats.rows_upserted,
    )
    return stats


async def export_region_tree_review_batches(
    output_dir: Path,
    *,
    limit_roots: int = 24,
    max_regions_per_batch: int = 300,
    sample_size: int = 25,
) -> RegionTreeReviewBatchStats:
    """Export regional hierarchy sections for GPT review workers."""
    await apply_migrations()
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = RegionTreeReviewBatchStats(output_dir=output_dir)
    engine = get_engine()

    async with engine.begin() as conn:
        root_rows = (
            (
                await conn.execute(
                    text("""
                        WITH root_scores AS (
                            SELECT
                                rr.to_region_id AS root_region_id,
                                count(DISTINCT rr.from_region_id) AS direct_child_count
                            FROM wg_region_relationships rr
                            WHERE rr.status = 'accepted'
                              AND rr.relation <> 'overlaps'
                            GROUP BY rr.to_region_id
                        )
                        SELECT
                            rs.root_region_id,
                            r.canonical_name AS root_name,
                            r.kind,
                            rs.direct_child_count
                        FROM root_scores rs
                        JOIN wg_regions r ON r.id = rs.root_region_id
                        ORDER BY rs.direct_child_count DESC, r.canonical_name
                        LIMIT :limit_roots
                    """),
                    {"limit_roots": limit_roots},
                )
            )
            .mappings()
            .fetchall()
        )

        for root in root_rows:
            batch_key = stable_key("region-tree-review", root["root_region_id"], root["root_name"])
            region_rows = (
                (
                    await conn.execute(
                        text("""
                            WITH RECURSIVE descendants(region_id, depth_from_root, path_region_ids) AS (
                                SELECT
                                    CAST(:root_region_id AS text),
                                    0,
                                    ARRAY[CAST(:root_region_id AS text)]
                                UNION ALL
                                SELECT
                                    rr.from_region_id,
                                    d.depth_from_root + 1,
                                    d.path_region_ids || rr.from_region_id
                                FROM wg_region_relationships rr
                                JOIN descendants d ON d.region_id = rr.to_region_id
                                WHERE rr.status = 'accepted'
                                  AND rr.relation <> 'overlaps'
                                  AND NOT rr.from_region_id = ANY(d.path_region_ids)
                                  AND d.depth_from_root < 8
                            ),
                            ranked AS (
                                SELECT DISTINCT ON (d.region_id)
                                    d.region_id,
                                    r.canonical_name,
                                    r.kind,
                                    r.display_title,
                                    r.wikipedia_title,
                                    d.depth_from_root,
                                    d.path_region_ids,
                                    coalesce(g.genre_edges, 0) AS genre_edges
                                FROM descendants d
                                JOIN wg_regions r ON r.id = d.region_id
                                LEFT JOIN (
                                    SELECT region_id, count(*) AS genre_edges
                                    FROM wg_region_genre_relationships
                                    WHERE status = 'accepted'
                                    GROUP BY region_id
                                ) g ON g.region_id = d.region_id
                                ORDER BY d.region_id, d.depth_from_root, r.canonical_name
                            )
                            SELECT *
                            FROM ranked
                            ORDER BY depth_from_root, genre_edges DESC, canonical_name
                            LIMIT :max_regions
                        """),
                        {
                            "root_region_id": root["root_region_id"],
                            "max_regions": max_regions_per_batch,
                        },
                    )
                )
                .mappings()
                .fetchall()
            )
            region_ids = [row["region_id"] for row in region_rows]
            region_edge_rows = []
            genre_edge_rows = []
            merge_rows = []
            if region_ids:
                region_edge_rows = (
                    (
                        await conn.execute(
                            text("""
                                SELECT
                                    rr.from_region_id,
                                    from_r.canonical_name AS from_name,
                                    rr.to_region_id,
                                    to_r.canonical_name AS to_name,
                                    rr.relation,
                                    rr.source_type,
                                    rr.source_title,
                                    rr.source_section,
                                    rr.evidence_text,
                                    rr.confidence,
                                    rr.status,
                                    rr.review_reason
                                FROM wg_region_relationships rr
                                JOIN wg_regions from_r ON from_r.id = rr.from_region_id
                                JOIN wg_regions to_r ON to_r.id = rr.to_region_id
                                WHERE rr.status = 'accepted'
                                  AND rr.from_region_id = ANY(:region_ids)
                                  AND rr.to_region_id = ANY(:region_ids)
                                ORDER BY from_r.canonical_name, to_r.canonical_name, rr.relation
                            """),
                            {"region_ids": region_ids},
                        )
                    )
                    .mappings()
                    .fetchall()
                )
                genre_edge_rows = (
                    (
                        await conn.execute(
                            text("""
                                SELECT
                                    rgr.region_id,
                                    reg.canonical_name AS region_name,
                                    rgr.genre_id,
                                    g.wikipedia_title AS genre_title,
                                    rgr.relation,
                                    rgr.source_type,
                                    rgr.source_title,
                                    rgr.source_section,
                                    rgr.evidence_text,
                                    rgr.confidence,
                                    rgr.status,
                                    rgr.review_reason
                                FROM wg_region_genre_relationships rgr
                                JOIN wg_regions reg ON reg.id = rgr.region_id
                                JOIN wg_genres g ON g.id = rgr.genre_id
                                WHERE rgr.status = 'accepted'
                                  AND rgr.region_id = ANY(:region_ids)
                                ORDER BY reg.canonical_name, g.wikipedia_title, rgr.relation
                            """),
                            {"region_ids": region_ids},
                        )
                    )
                    .mappings()
                    .fetchall()
                )
                merge_rows = (
                    (
                        await conn.execute(
                            text("""
                                SELECT
                                    left_region_id,
                                    right_region_id,
                                    left_name,
                                    right_name,
                                    score,
                                    status,
                                    evidence
                                FROM wg_region_merge_candidates
                                WHERE left_region_id = ANY(:region_ids)
                                   OR right_region_id = ANY(:region_ids)
                                ORDER BY score DESC, left_name, right_name
                                LIMIT 100
                            """),
                            {"region_ids": region_ids},
                        )
                    )
                    .mappings()
                    .fetchall()
                )

            payload = {
                "batch_key": batch_key,
                "root_region_id": root["root_region_id"],
                "root_name": root["root_name"],
                "root_kind": root["kind"],
                "review_standards": [
                    "Review only the regional graph: region nodes, region-region hierarchy, parallel/cultural/diaspora/historical relationships, and region-to-genre attachments.",
                    "Flag duplicate regions, especially duplicate Music of country/territory/city/cultural-region nodes with equivalent scope.",
                    "Region direction is child to broader parent. Countries, territories, cities, islands, and subregions should point upward to the most specific supported parent and also to justified parallel cultural regions.",
                    "Do not collapse countries into source colors or style genres. Countries and territories should inherit regional context through region edges.",
                    "Regional genre edges should attach to the most specific supported region first, then inherit upward through accepted region-region relationships.",
                    "List/category evidence is valid when it clearly groups countries/territories/regions or names genres within a regional section.",
                    "Flag missing parents for smaller territories, cities, islands, cultural regions, diaspora regions, historical regions, indigenous/traditional contexts, and regional lists that should be represented.",
                    "Flag region-to-genre edges that are too broad, wrong, artifact-like, or should belong under a more specific region.",
                ],
                "regions": [dict(row) for row in region_rows],
                "region_edges": [dict(row) for row in region_edge_rows],
                "region_genre_edges": [dict(row) for row in genre_edge_rows],
                "region_merge_candidates": [dict(row) for row in merge_rows],
                "expected_output_jsonl_schema": {
                    "finding_type": "duplicate_region|wrong_region_parent|missing_region_parent|wrong_region_direction|wrong_region_genre|missing_region_genre|missing_region|bad_region_node|bad_relationship|kind_mismatch|other",
                    "severity": "low|medium|high",
                    "region_id": "optional primary region id",
                    "related_region_id": "optional related region id",
                    "genre_id": "optional genre id for region-to-genre findings",
                    "title": "optional primary title",
                    "related_title": "optional related title or genre title",
                    "recommendation": "specific action/review note",
                    "evidence": "short evidence object",
                },
            }
            safe_title = re.sub(r"[^a-z0-9]+", "-", root["root_name"].lower()).strip("-")
            output_path = output_dir / f"{safe_title or root['root_region_id']}.json"
            output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

            await conn.execute(
                text("""
                    INSERT INTO wg_region_tree_review_batches (
                        batch_key,
                        root_region_id,
                        root_name,
                        region_count,
                        region_edge_count,
                        genre_edge_count,
                        output_path,
                        status,
                        reviewer_model,
                        raw_payload,
                        updated_at
                    )
                    VALUES (
                        :batch_key,
                        :root_region_id,
                        :root_name,
                        :region_count,
                        :region_edge_count,
                        :genre_edge_count,
                        :output_path,
                        'exported',
                        'gpt-5.4-mini',
                        :raw_payload,
                        now()
                    )
                    ON CONFLICT (batch_key) DO UPDATE
                    SET region_count = excluded.region_count,
                        region_edge_count = excluded.region_edge_count,
                        genre_edge_count = excluded.genre_edge_count,
                        output_path = excluded.output_path,
                        status = excluded.status,
                        reviewer_model = excluded.reviewer_model,
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                """),
                {
                    "batch_key": batch_key,
                    "root_region_id": root["root_region_id"],
                    "root_name": root["root_name"],
                    "region_count": len(region_rows),
                    "region_edge_count": len(region_edge_rows),
                    "genre_edge_count": len(genre_edge_rows),
                    "output_path": str(output_path),
                    "raw_payload": json.dumps(
                        {
                            "region_merge_candidates": len(merge_rows),
                            "max_regions_per_batch": max_regions_per_batch,
                        }
                    ),
                },
            )
            stats.batches_exported += 1
            stats.regions_exported += len(region_rows)
            stats.region_edges_exported += len(region_edge_rows)
            stats.genre_edges_exported += len(genre_edge_rows)
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{root['root_name']}: regions={len(region_rows)} region_edges={len(region_edge_rows)} genre_edges={len(genre_edge_rows)} file={output_path}"
                )

    return stats


async def import_region_tree_review_findings(
    input_path: Path,
    *,
    batch_key: str | None = None,
    reviewer_model: str = "gpt-5.4-mini",
) -> RegionTreeReviewFindingImportStats:
    """Import GPT regional tree review JSONL findings into staging."""
    await apply_migrations()
    stats = RegionTreeReviewFindingImportStats()
    allowed_types = {
        "duplicate_region",
        "wrong_region_parent",
        "missing_region_parent",
        "wrong_region_direction",
        "wrong_region_genre",
        "missing_region_genre",
        "missing_region",
        "bad_region_node",
        "bad_relationship",
        "kind_mismatch",
        "other",
    }
    type_aliases = {
        "wrong_parent": "wrong_region_parent",
        "missing_parent": "missing_region_parent",
        "wrong_direction": "wrong_region_direction",
        "wrong_genre_edge": "wrong_region_genre",
        "overbroad_genre_edge": "wrong_region_genre",
        "missing_genre_edge": "missing_region_genre",
    }
    allowed_severities = {"low", "medium", "high"}
    engine = get_engine()

    async with engine.begin() as conn:
        with input_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                stats.rows_seen += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    stats.rows_rejected += 1
                    stats.errors.append(f"line {line_number}: invalid JSON: {exc}")
                    continue

                finding_type = type_aliases.get(
                    payload.get("finding_type") or "other",
                    payload.get("finding_type") or "other",
                )
                severity = payload.get("severity") or "medium"
                if finding_type not in allowed_types:
                    stats.rows_rejected += 1
                    stats.errors.append(f"line {line_number}: invalid finding_type {finding_type}")
                    continue
                if severity not in allowed_severities:
                    stats.rows_rejected += 1
                    stats.errors.append(f"line {line_number}: invalid severity {severity}")
                    continue
                recommendation = payload.get("recommendation")
                if not recommendation:
                    stats.rows_rejected += 1
                    stats.errors.append(f"line {line_number}: missing recommendation")
                    continue

                evidence_payload = payload.get("evidence") or {}
                row_batch_key = payload.get("batch_key") or batch_key
                if not row_batch_key and isinstance(evidence_payload, dict):
                    row_batch_key = evidence_payload.get("batch_key")
                if not row_batch_key:
                    row_batch_key = stable_key("region-tree-review-import", str(input_path))
                    await conn.execute(
                        text("""
                            INSERT INTO wg_region_tree_review_batches (
                                batch_key,
                                root_name,
                                output_path,
                                status,
                                reviewer_model,
                                raw_payload,
                                updated_at
                            )
                            VALUES (
                                :batch_key,
                                :root_name,
                                :output_path,
                                'reviewed',
                                :reviewer_model,
                                :raw_payload,
                                now()
                            )
                            ON CONFLICT (batch_key) DO UPDATE
                            SET status = 'reviewed',
                                reviewer_model = excluded.reviewer_model,
                                raw_payload = wg_region_tree_review_batches.raw_payload || excluded.raw_payload,
                                updated_at = now()
                        """),
                        {
                            "batch_key": row_batch_key,
                            "root_name": input_path.stem,
                            "output_path": str(input_path),
                            "reviewer_model": reviewer_model,
                            "raw_payload": json.dumps({"imported_from": str(input_path)}),
                        },
                    )

                finding_key = stable_key(
                    "region-tree-finding",
                    row_batch_key,
                    finding_type,
                    payload.get("region_id") or "",
                    payload.get("related_region_id") or "",
                    payload.get("genre_id") or "",
                    recommendation,
                )
                await conn.execute(
                    text("""
                        INSERT INTO wg_region_tree_review_findings (
                            finding_key,
                            batch_key,
                            finding_type,
                            severity,
                            region_id,
                            related_region_id,
                            genre_id,
                            title,
                            related_title,
                            recommendation,
                            evidence,
                            reviewer_model,
                            status,
                            updated_at
                        )
                        VALUES (
                            :finding_key,
                            :batch_key,
                            :finding_type,
                            :severity,
                            :region_id,
                            :related_region_id,
                            :genre_id,
                            :title,
                            :related_title,
                            :recommendation,
                            :evidence,
                            :reviewer_model,
                            'needs_review',
                            now()
                        )
                        ON CONFLICT (finding_key) DO UPDATE
                        SET severity = excluded.severity,
                            title = excluded.title,
                            related_title = excluded.related_title,
                            recommendation = excluded.recommendation,
                            evidence = excluded.evidence,
                            reviewer_model = excluded.reviewer_model,
                            updated_at = now()
                    """),
                    {
                        "finding_key": finding_key,
                        "batch_key": row_batch_key,
                        "finding_type": finding_type,
                        "severity": severity,
                        "region_id": payload.get("region_id"),
                        "related_region_id": payload.get("related_region_id"),
                        "genre_id": payload.get("genre_id"),
                        "title": payload.get("title"),
                        "related_title": payload.get("related_title"),
                        "recommendation": recommendation,
                        "evidence": json.dumps(evidence_payload),
                        "reviewer_model": reviewer_model,
                    },
                )
                stats.rows_imported += 1

    return stats
