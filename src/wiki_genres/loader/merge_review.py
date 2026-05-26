"""Graph-wide merge candidate detection and tree review batch export."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)


@dataclass
class MergeCandidateStats:
    rows_seen: int = 0
    rows_upserted: int = 0
    deleted_existing: int = 0
    sample: list[str] = field(default_factory=list)


@dataclass
class TreeReviewBatchStats:
    batches_exported: int = 0
    nodes_exported: int = 0
    edges_exported: int = 0
    output_dir: Path | None = None
    sample: list[str] = field(default_factory=list)


@dataclass
class TreeReviewFindingImportStats:
    rows_seen: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)


def stable_key(*parts: str) -> str:
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:24]


def normalize_label(label: str) -> str:
    clean = label.lower()
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = clean.replace("&", " and ")
    clean = re.sub(r"\b(music|genre|style|styles|scene|scenes)\b", " ", clean)
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return " ".join(clean.split())


async def index_genre_merge_candidates(
    *,
    reset: bool = False,
    limit: int = 5000,
    sample_size: int = 25,
) -> MergeCandidateStats:
    """Stage likely duplicate/merge candidates without modifying genre rows."""
    await apply_migrations()
    stats = MergeCandidateStats()
    engine = get_engine()

    async with engine.begin() as conn:
        if reset:
            deleted = await conn.execute(text("DELETE FROM wg_genre_merge_candidates"))
            stats.deleted_existing = deleted.rowcount or 0

        rows = (
            (
                await conn.execute(
                    text("""
                        WITH active_genres AS (
                            SELECT
                                g.id,
                                g.wikipedia_title,
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            lower(g.wikipedia_title),
                                            '\\([^)]*\\)',
                                            ' ',
                                            'g'
                                        ),
                                        '\\m(music|genre|style|styles|scene|scenes)\\M',
                                        ' ',
                                        'g'
                                    ),
                                    '[^a-z0-9]+',
                                    ' ',
                                    'g'
                                ) AS normalized_title,
                                g.monthly_views_p30
                            FROM wg_genres g
                            WHERE g.deleted_at IS NULL
                              AND g.is_non_genre = false
                        ),
                        title_pairs AS (
                            SELECT
                                LEAST(a.id, b.id) AS left_genre_id,
                                GREATEST(a.id, b.id) AS right_genre_id,
                                CASE WHEN a.id < b.id THEN a.wikipedia_title ELSE b.wikipedia_title END AS left_title,
                                CASE WHEN a.id < b.id THEN b.wikipedia_title ELSE a.wikipedia_title END AS right_title,
                                similarity(a.normalized_title, b.normalized_title) AS title_similarity,
                                a.normalized_title = b.normalized_title AS normalized_match
                            FROM active_genres a
                            JOIN active_genres b ON a.id < b.id
                            WHERE (
                                a.normalized_title = b.normalized_title
                                OR similarity(a.normalized_title, b.normalized_title) >= 0.82
                            )
                        ),
                        alias_pairs AS (
                            SELECT
                                LEAST(a.genre_id, b.genre_id) AS left_genre_id,
                                GREATEST(a.genre_id, b.genre_id) AS right_genre_id,
                                count(DISTINCT lower(a.alias)) AS alias_overlap
                            FROM wg_aliases a
                            JOIN wg_aliases b
                              ON lower(a.alias) = lower(b.alias)
                             AND a.genre_id < b.genre_id
                            JOIN active_genres ag1 ON ag1.id = a.genre_id
                            JOIN active_genres ag2 ON ag2.id = b.genre_id
                            GROUP BY 1, 2
                        ),
                        redirect_pairs AS (
                            SELECT
                                LEAST(r.to_genre_id, g.id) AS left_genre_id,
                                GREATEST(r.to_genre_id, g.id) AS right_genre_id,
                                true AS redirect_match
                            FROM wg_redirects r
                            JOIN active_genres g
                              ON lower(g.wikipedia_title) = lower(r.from_title)
                             AND g.id <> r.to_genre_id
                        ),
                        graph_parent_pairs AS (
                            SELECT
                                LEAST(e1.to_genre_id, e2.to_genre_id) AS left_genre_id,
                                GREATEST(e1.to_genre_id, e2.to_genre_id) AS right_genre_id,
                                count(DISTINCT e1.from_genre_id) AS shared_parent_count
                            FROM wg_edges e1
                            JOIN wg_edges e2
                              ON e1.from_genre_id = e2.from_genre_id
                             AND e1.to_genre_id < e2.to_genre_id
                            JOIN active_genres g1 ON g1.id = e1.to_genre_id
                            JOIN active_genres g2 ON g2.id = e2.to_genre_id
                            WHERE e1.is_ignored = false
                              AND e2.is_ignored = false
                              AND e1.relation IN ('subgenre', 'derivative', 'fusion_genre')
                              AND e2.relation IN ('subgenre', 'derivative', 'fusion_genre')
                            GROUP BY 1, 2
                        ),
                        graph_child_pairs AS (
                            SELECT
                                LEAST(e1.from_genre_id, e2.from_genre_id) AS left_genre_id,
                                GREATEST(e1.from_genre_id, e2.from_genre_id) AS right_genre_id,
                                count(DISTINCT e1.to_genre_id) AS shared_child_count
                            FROM wg_edges e1
                            JOIN wg_edges e2
                              ON e1.to_genre_id = e2.to_genre_id
                             AND e1.from_genre_id < e2.from_genre_id
                            JOIN active_genres g1 ON g1.id = e1.from_genre_id
                            JOIN active_genres g2 ON g2.id = e2.from_genre_id
                            WHERE e1.is_ignored = false
                              AND e2.is_ignored = false
                              AND e1.relation IN ('subgenre', 'derivative', 'fusion_genre')
                              AND e2.relation IN ('subgenre', 'derivative', 'fusion_genre')
                            GROUP BY 1, 2
                        ),
                        all_pairs AS (
                            SELECT left_genre_id, right_genre_id FROM title_pairs
                            UNION
                            SELECT left_genre_id, right_genre_id FROM alias_pairs
                            UNION
                            SELECT left_genre_id, right_genre_id FROM redirect_pairs
                        )
                        SELECT
                            p.left_genre_id,
                            p.right_genre_id,
                            left_g.wikipedia_title AS left_title,
                            right_g.wikipedia_title AS right_title,
                            coalesce(tp.title_similarity, similarity(left_g.normalized_title, right_g.normalized_title)) AS title_similarity,
                            coalesce(tp.normalized_match, left_g.normalized_title = right_g.normalized_title) AS normalized_match,
                            coalesce(ap.alias_overlap, 0) AS alias_overlap,
                            coalesce(rp.redirect_match, false) AS redirect_match,
                            coalesce(gpp.shared_parent_count, 0) AS shared_parent_count,
                            coalesce(gcp.shared_child_count, 0) AS shared_child_count,
                            LEAST(
                                1.0,
                                (
                                    coalesce(tp.title_similarity, similarity(left_g.normalized_title, right_g.normalized_title)) * 0.52
                                    + CASE WHEN coalesce(tp.normalized_match, left_g.normalized_title = right_g.normalized_title) THEN 0.22 ELSE 0 END
                                    + LEAST(coalesce(ap.alias_overlap, 0), 3) * 0.08
                                    + CASE WHEN coalesce(rp.redirect_match, false) THEN 0.18 ELSE 0 END
                                    + LEAST(coalesce(gpp.shared_parent_count, 0), 4) * 0.025
                                    + LEAST(coalesce(gcp.shared_child_count, 0), 4) * 0.02
                                )
                            ) AS score
                        FROM all_pairs p
                        JOIN active_genres left_g ON left_g.id = p.left_genre_id
                        JOIN active_genres right_g ON right_g.id = p.right_genre_id
                        LEFT JOIN title_pairs tp
                          ON tp.left_genre_id = p.left_genre_id
                         AND tp.right_genre_id = p.right_genre_id
                        LEFT JOIN alias_pairs ap
                          ON ap.left_genre_id = p.left_genre_id
                         AND ap.right_genre_id = p.right_genre_id
                        LEFT JOIN redirect_pairs rp
                          ON rp.left_genre_id = p.left_genre_id
                         AND rp.right_genre_id = p.right_genre_id
                        LEFT JOIN graph_parent_pairs gpp
                          ON gpp.left_genre_id = p.left_genre_id
                         AND gpp.right_genre_id = p.right_genre_id
                        LEFT JOIN graph_child_pairs gcp
                          ON gcp.left_genre_id = p.left_genre_id
                         AND gcp.right_genre_id = p.right_genre_id
                        WHERE (
                            coalesce(tp.normalized_match, left_g.normalized_title = right_g.normalized_title)
                            OR coalesce(ap.alias_overlap, 0) > 0
                            OR coalesce(rp.redirect_match, false)
                            OR coalesce(tp.title_similarity, similarity(left_g.normalized_title, right_g.normalized_title)) >= 0.86
                        )
                        ORDER BY score DESC, title_similarity DESC, left_title, right_title
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
                "merge",
                row_dict["left_genre_id"],
                row_dict["right_genre_id"],
            )
            status = "needs_review"
            reason = "Similarity pass candidate."
            if row_dict["redirect_match"]:
                status = "already_redirect"
                reason = "Redirect evidence already links the labels."
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_merge_candidates (
                        candidate_key,
                        left_genre_id,
                        right_genre_id,
                        left_title,
                        right_title,
                        score,
                        title_similarity,
                        normalized_match,
                        alias_overlap,
                        redirect_match,
                        shared_parent_count,
                        shared_child_count,
                        evidence,
                        status,
                        review_reason,
                        reviewer_model,
                        updated_at
                    )
                    VALUES (
                        :candidate_key,
                        :left_genre_id,
                        :right_genre_id,
                        :left_title,
                        :right_title,
                        :score,
                        :title_similarity,
                        :normalized_match,
                        :alias_overlap,
                        :redirect_match,
                        :shared_parent_count,
                        :shared_child_count,
                        :evidence,
                        :status,
                        :review_reason,
                        'deterministic-merge-similarity-v1',
                        now()
                    )
                    ON CONFLICT (candidate_key) DO UPDATE
                    SET score = excluded.score,
                        title_similarity = excluded.title_similarity,
                        normalized_match = excluded.normalized_match,
                        alias_overlap = excluded.alias_overlap,
                        redirect_match = excluded.redirect_match,
                        shared_parent_count = excluded.shared_parent_count,
                        shared_child_count = excluded.shared_child_count,
                        evidence = excluded.evidence,
                        status = excluded.status,
                        review_reason = excluded.review_reason,
                        reviewer_model = excluded.reviewer_model,
                        updated_at = now()
                """),
                {
                    **row_dict,
                    "candidate_key": key,
                    "evidence": json.dumps(
                        {
                            "normalized_left": normalize_label(row_dict["left_title"]),
                            "normalized_right": normalize_label(row_dict["right_title"]),
                            "signals": {
                                "title_similarity": row_dict["title_similarity"],
                                "normalized_match": row_dict["normalized_match"],
                                "alias_overlap": row_dict["alias_overlap"],
                                "redirect_match": row_dict["redirect_match"],
                                "shared_parent_count": row_dict["shared_parent_count"],
                                "shared_child_count": row_dict["shared_child_count"],
                            },
                        }
                    ),
                    "status": status,
                    "review_reason": reason,
                },
            )
            stats.rows_upserted += 1
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{row_dict['left_title']} <> {row_dict['right_title']} score={row_dict['score']:.2f}"
                )

    logger.info(
        "genre_merge_candidates_indexed",
        rows_seen=stats.rows_seen,
        rows_upserted=stats.rows_upserted,
    )
    return stats


async def export_tree_review_batches(
    output_dir: Path,
    *,
    limit_roots: int = 8,
    max_nodes_per_batch: int = 350,
    sample_size: int = 25,
) -> TreeReviewBatchStats:
    """Export Music-root tree sections for GPT review workers."""
    await apply_migrations()
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = TreeReviewBatchStats(output_dir=output_dir)
    engine = get_engine()

    async with engine.begin() as conn:
        root_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            r.root_genre_id,
                            root_g.wikipedia_title AS root_title,
                            count(DISTINCT r.genre_id) AS node_count
                        FROM wg_music_reachable_parents r
                        JOIN wg_genres root_g ON root_g.id = r.root_genre_id
                        GROUP BY r.root_genre_id, root_g.wikipedia_title
                        ORDER BY node_count DESC, root_g.wikipedia_title
                        LIMIT :limit_roots
                    """),
                    {"limit_roots": limit_roots},
                )
            )
            .mappings()
            .fetchall()
        )

        for root in root_rows:
            batch_key = stable_key("tree-review", root["root_genre_id"], root["root_title"])
            node_rows = (
                (
                    await conn.execute(
                        text("""
                            SELECT DISTINCT ON (r.genre_id)
                                r.genre_id,
                                g.wikipedia_title,
                                g.summary,
                                g.monthly_views_p30,
                                r.depth_from_music,
                                r.path_genre_ids
                            FROM wg_music_reachable_parents r
                            JOIN wg_genres g ON g.id = r.genre_id
                            WHERE r.root_genre_id = :root_genre_id
                            ORDER BY r.genre_id, r.depth_from_music, g.wikipedia_title
                            LIMIT :max_nodes
                        """),
                        {
                            "root_genre_id": root["root_genre_id"],
                            "max_nodes": max_nodes_per_batch,
                        },
                    )
                )
                .mappings()
                .fetchall()
            )
            node_ids = [row["genre_id"] for row in node_rows]
            edge_rows = []
            if node_ids:
                edge_rows = (
                    (
                        await conn.execute(
                            text("""
                                SELECT
                                    e.from_genre_id,
                                    from_g.wikipedia_title AS from_title,
                                    e.to_genre_id,
                                    to_g.wikipedia_title AS to_title,
                                    e.relation,
                                    e.evidence_relation,
                                    e.source,
                                    e.ordinal
                                FROM wg_edges e
                                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                                JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                                WHERE e.is_ignored = false
                                  AND e.from_genre_id = ANY(:node_ids)
                                  AND e.to_genre_id = ANY(:node_ids)
                                  AND e.relation IN ('subgenre', 'derivative', 'fusion_genre', 'related_genre')
                                ORDER BY from_g.wikipedia_title, to_g.wikipedia_title, e.relation, e.source, e.ordinal
                            """),
                            {"node_ids": node_ids},
                        )
                    )
                    .mappings()
                    .fetchall()
                )
            merge_rows = (
                (
                    await conn.execute(
                        text("""
                            SELECT left_genre_id,
                                   right_genre_id,
                                   left_title,
                                   right_title,
                                   score,
                                   status,
                                   evidence
                            FROM wg_genre_merge_candidates
                            WHERE left_genre_id = ANY(:node_ids)
                               OR right_genre_id = ANY(:node_ids)
                            ORDER BY score DESC, left_title, right_title
                            LIMIT 80
                        """),
                        {"node_ids": node_ids or ["__none__"]},
                    )
                )
                .mappings()
                .fetchall()
            )

            payload = {
                "batch_key": batch_key,
                "root_genre_id": root["root_genre_id"],
                "root_title": root["root_title"],
                "review_standards": [
                    "Identify duplicate or near-duplicate nodes that should merge, but do not merge regional pages into broad style genres.",
                    "Flag non-genre or artifact pages that survived curation.",
                    "Check parent-child direction: parent should be broader; child should be a specific genre/style/scene.",
                    "Prefer specific parents over broad umbrella spam.",
                    "Fusion is directional: selected child may be a fusion of parents, but parents should not be child-spammed.",
                    "Related genre evidence is valid only when the evidence relation and source justify it.",
                    "Regional relationships should attach to the most specific supported region and inherit upward.",
                ],
                "nodes": [dict(row) for row in node_rows],
                "edges": [dict(row) for row in edge_rows],
                "merge_candidates": [dict(row) for row in merge_rows],
                "expected_output_jsonl_schema": {
                    "finding_type": "merge_candidate|wrong_parent|missing_parent|wrong_direction|non_genre|duplicate_region|bad_relationship|missing_relationship|other",
                    "severity": "low|medium|high",
                    "genre_id": "optional primary node id",
                    "related_genre_id": "optional related node id",
                    "title": "optional primary title",
                    "related_title": "optional related title",
                    "recommendation": "specific action/review note",
                    "evidence": "short evidence object",
                },
            }
            safe_title = re.sub(r"[^a-z0-9]+", "-", root["root_title"].lower()).strip("-")
            output_path = output_dir / f"{safe_title or root['root_genre_id']}.json"
            output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

            await conn.execute(
                text("""
                    INSERT INTO wg_tree_review_batches (
                        batch_key,
                        root_genre_id,
                        root_title,
                        node_count,
                        edge_count,
                        output_path,
                        status,
                        reviewer_model,
                        raw_payload,
                        updated_at
                    )
                    VALUES (
                        :batch_key,
                        :root_genre_id,
                        :root_title,
                        :node_count,
                        :edge_count,
                        :output_path,
                        'exported',
                        'gpt-5.4-mini',
                        :raw_payload,
                        now()
                    )
                    ON CONFLICT (batch_key) DO UPDATE
                    SET node_count = excluded.node_count,
                        edge_count = excluded.edge_count,
                        output_path = excluded.output_path,
                        status = excluded.status,
                        reviewer_model = excluded.reviewer_model,
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                """),
                {
                    "batch_key": batch_key,
                    "root_genre_id": root["root_genre_id"],
                    "root_title": root["root_title"],
                    "node_count": len(node_rows),
                    "edge_count": len(edge_rows),
                    "output_path": str(output_path),
                    "raw_payload": json.dumps(
                        {
                            "merge_candidates": len(merge_rows),
                            "max_nodes_per_batch": max_nodes_per_batch,
                        }
                    ),
                },
            )
            stats.batches_exported += 1
            stats.nodes_exported += len(node_rows)
            stats.edges_exported += len(edge_rows)
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{root['root_title']}: nodes={len(node_rows)} edges={len(edge_rows)} file={output_path}"
                )

    return stats


async def import_tree_review_findings(
    input_path: Path,
    *,
    batch_key: str | None = None,
    reviewer_model: str = "gpt-5.4-mini",
) -> TreeReviewFindingImportStats:
    """Import GPT tree review JSONL findings into staging."""
    await apply_migrations()
    stats = TreeReviewFindingImportStats()
    allowed_types = {
        "merge_candidate",
        "wrong_parent",
        "missing_parent",
        "wrong_direction",
        "non_genre",
        "duplicate_region",
        "bad_relationship",
        "missing_relationship",
        "other",
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

                finding_type = payload.get("finding_type") or "other"
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

                row_batch_key = payload.get("batch_key") or batch_key
                if not row_batch_key:
                    row_batch_key = stable_key("tree-review-import", str(input_path))
                    await conn.execute(
                        text("""
                            INSERT INTO wg_tree_review_batches (
                                batch_key,
                                root_title,
                                output_path,
                                status,
                                reviewer_model,
                                raw_payload,
                                updated_at
                            )
                            VALUES (
                                :batch_key,
                                :root_title,
                                :output_path,
                                'reviewed',
                                :reviewer_model,
                                :raw_payload,
                                now()
                            )
                            ON CONFLICT (batch_key) DO UPDATE
                            SET status = 'reviewed',
                                reviewer_model = excluded.reviewer_model,
                                raw_payload = wg_tree_review_batches.raw_payload || excluded.raw_payload,
                                updated_at = now()
                        """),
                        {
                            "batch_key": row_batch_key,
                            "root_title": input_path.stem,
                            "output_path": str(input_path),
                            "reviewer_model": reviewer_model,
                            "raw_payload": json.dumps({"imported_from": str(input_path)}),
                        },
                    )

                finding_key = stable_key(
                    "tree-finding",
                    row_batch_key,
                    finding_type,
                    payload.get("genre_id") or "",
                    payload.get("related_genre_id") or "",
                    recommendation,
                )
                await conn.execute(
                    text("""
                        INSERT INTO wg_tree_review_findings (
                            finding_key,
                            batch_key,
                            finding_type,
                            severity,
                            genre_id,
                            related_genre_id,
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
                            :genre_id,
                            :related_genre_id,
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
                        "genre_id": payload.get("genre_id"),
                        "related_genre_id": payload.get("related_genre_id"),
                        "title": payload.get("title"),
                        "related_title": payload.get("related_title"),
                        "recommendation": recommendation,
                        "evidence": json.dumps(payload.get("evidence") or {}),
                        "reviewer_model": reviewer_model,
                    },
                )
                stats.rows_imported += 1

    return stats
