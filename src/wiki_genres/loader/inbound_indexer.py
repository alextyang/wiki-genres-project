"""Derived inbound relationship indexer.

The loader stores upstream facts in their source direction. Wikidata
``subclass_of`` points from child to parent, which is useful evidence but does
not directly show up as a child under the parent in the explorer. This module
materializes conservative high-confidence display edges and broader
``related_genre`` coverage edges with ``source='inbound_index'``. Reverse
coverage edges store inverse evidence labels like ``subgenre_of`` so the rows
remain useful without becoming forward display edges.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

DISPLAY_RELATIONS = {"subgenre", "derivative", "fusion_genre"}
DIRECT_PARENT_SOURCE = "wikidata"
DIRECT_PARENT_RELATION = "subclass_of"
FUSION_RELATION = "fusion_genre"
INFERRED_SOURCE = "inbound_index"
INFERRED_SUBGENRE_RELATION = "subgenre"
RELATED_RELATION = "related_genre"
SUMMARY_EVIDENCE_RELATION = "summary_subgenre_of"

# Abstract classifier rows should not become visible explorer parents.
EXCLUDED_PARENT_QIDS = {"Q188451", "Q2944929"}  # music genre, musical style
EXCLUDED_PARENT_TITLES = {"Music genre", "Musical style"}
EXCLUDED_PARENT_TITLES_LOWER = {title.lower() for title in EXCLUDED_PARENT_TITLES}
TAXONOMY_OBJECT_STOP_WORDS = {
    "that",
    "which",
    "whose",
    "found",
    "originating",
    "originated",
    "developed",
    "emerged",
    "rooted",
    "influenced",
}
TAXONOMY_CUE_RE = re.compile(
    r"\b(?:is|are|was|were)\s+"
    r"(?:(?:one|part)\s+of\s+)?"
    r"(?:(?:a|an|the)\s+)?"
    r"(?:"
    r"subgenre|sub\s+genre|kind|type|form|style|genre|variety|branch|offshoot|variant"
    r")\s+of\b"
)

INVERSE_EVIDENCE_RELATIONS = {
    "subgenre": "subgenre_of",
    "derivative": "derivative_of",
    "fusion_genre": "fusion_of",
    "stylistic_origin": "stylistic_origin_of",
    "cultural_origin": "cultural_origin_of",
    "regional_scene": "regional_scene_of",
    "local_scene": "local_scene_of",
    "other_name": "alias_of",
    "influenced_by": "influence_on",
    "subclass_of": "subclass_of_parent",
    "part_of": "contains_part",
    "instance_of": "classifies",
}


@dataclass(frozen=True)
class InferredEdge:
    parent_id: str
    parent_title: str
    child_id: str
    child_title: str
    relation: str
    reason: str
    evidence_relation: str | None = None
    source: str = INFERRED_SOURCE


@dataclass
class InboundIndexStats:
    candidates: int = 0
    inserted: int = 0
    display_inserted: int = 0
    related_inserted: int = 0
    deleted_existing: int = 0
    skipped_self_loop: int = 0
    skipped_excluded_parent: int = 0
    skipped_existing_direct: int = 0
    skipped_existing_related: int = 0
    skipped_ancestor_shortcut: int = 0
    skipped_duplicate_candidate: int = 0
    skipped_promoted_region_node: int = 0
    dry_run: bool = False
    sample: list[InferredEdge] = field(default_factory=list)


def _normalize_text(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[-‐‑‒–—/]", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _title_variants(title: str) -> tuple[str, ...]:
    variants = {_normalize_text(title)}
    without_parenthetical = re.sub(r"\s*\([^)]*\)", "", title).strip()
    if without_parenthetical:
        variants.add(_normalize_text(without_parenthetical))
    return tuple(sorted(v for v in variants if v))


def _find_title(text: str, title: str) -> int:
    positions: list[int] = []
    for variant in _title_variants(title):
        match = re.search(rf"(?:^| ){re.escape(variant)}(?: |$)", text)
        if match:
            positions.append(match.start())
    return min(positions) if positions else -1


def _taxonomy_object_after_cue(summary: str, cue_end: int) -> str:
    tokens = summary[cue_end:].split()
    object_tokens: list[str] = []
    for token in tokens[:36]:
        if token in TAXONOMY_OBJECT_STOP_WORDS:
            break
        object_tokens.append(token)
    return " ".join(object_tokens)


def _summary_supported_reverse_relation(
    summary: str | None,
    child_title: str,
    parent_title: str,
) -> str | None:
    """Return a display relation when summary prose confirms parent -> child.

    The parser stores many upstream edges in their source direction. A summary
    phrase like "X is a subgenre of Y" is stronger than pageview/year heuristics
    for deciding that Y should be the display parent of X.
    """
    if not summary:
        return None

    normalized_summary = _normalize_text(summary)
    child_pos = _find_title(normalized_summary, child_title)
    if child_pos < 0:
        return None

    for cue in TAXONOMY_CUE_RE.finditer(normalized_summary):
        if child_pos > cue.start():
            continue
        taxonomy_object = _taxonomy_object_after_cue(normalized_summary, cue.end())
        if _find_title(taxonomy_object, parent_title) >= 0:
            return INFERRED_SUBGENRE_RELATION

    return None


def _has_path(
    adjacency: dict[str, set[str]],
    start: str,
    target: str,
    *,
    min_depth: int = 1,
    max_depth: int = 8,
) -> bool:
    """Return true when ``target`` is reachable from ``start``.

    ``min_depth=2`` is used to identify ancestor shortcuts: a direct candidate
    parent already reaches the child through a more specific intermediate node.
    """
    if start == target and min_depth <= 0:
        return True

    queue: deque[tuple[str, int]] = deque((child, 1) for child in adjacency.get(start, ()))
    seen = {start}

    while queue:
        node, depth = queue.popleft()
        if node == target and depth >= min_depth:
            return True
        if depth >= max_depth or node in seen:
            continue
        seen.add(node)
        for child in adjacency.get(node, ()):
            queue.append((child, depth + 1))

    return False


def _build_adjacency(rows: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for parent_id, child_id in rows:
        if parent_id != child_id:
            adjacency[parent_id].add(child_id)
    return adjacency


def _is_excluded_parent(qid: str | None, title: str) -> bool:
    return (qid in EXCLUDED_PARENT_QIDS) or (title.lower() in EXCLUDED_PARENT_TITLES_LOWER)


def _reverse_coverage_relation(evidence_relation: str) -> str:  # noqa: ARG001
    """Reverse evidence is indexed for coverage, not as a visible child edge."""
    return RELATED_RELATION


def _reverse_evidence_relation(evidence_relation: str) -> str:
    """Return a human-meaningful inverse evidence label for reverse coverage."""
    return INVERSE_EVIDENCE_RELATIONS.get(evidence_relation, f"inverse_{evidence_relation}")


def _add_sample(stats: InboundIndexStats, edge: InferredEdge, sample_size: int) -> None:
    if len(stats.sample) < sample_size:
        stats.sample.append(edge)


def _remove_related_candidate_for_display(
    inferred: list[InferredEdge],
    sample: list[InferredEdge],
    parent_id: str,
    child_id: str,
) -> int:
    before = len(inferred)
    inferred[:] = [
        edge
        for edge in inferred
        if not (
            edge.parent_id == parent_id
            and edge.child_id == child_id
            and edge.relation == RELATED_RELATION
        )
    ]
    sample[:] = [
        edge
        for edge in sample
        if not (
            edge.parent_id == parent_id
            and edge.child_id == child_id
            and edge.relation == RELATED_RELATION
        )
    ]
    return before - len(inferred)


async def index_inbound_relationships(
    *,
    dry_run: bool = False,
    sample_size: int = 50,
    max_path_depth: int = 8,
) -> InboundIndexStats:
    """Materialize inferred relationship edges.

    Graph-visible relations are high-confidence only:
    - ``child subclass_of parent`` becomes ``parent subgenre child`` unless it
      is an ancestor shortcut.
    Other resolved inbound relationships become ``related_genre`` so they are
    indexed but ignored by the explorer's child renderer. This includes reverse
    ``fusion_genre`` evidence: the canonical visible direction remains
    component/source genre -> fusion child.
    """
    await apply_migrations()
    engine = get_engine()
    stats = InboundIndexStats(dry_run=dry_run)

    async with engine.connect() as conn:
        stats.skipped_promoted_region_node = int(
            await conn.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_edges e
                    LEFT JOIN wg_region_promoted_genres from_region
                      ON from_region.genre_id = e.from_genre_id
                    LEFT JOIN wg_region_promoted_genres to_region
                      ON to_region.genre_id = e.to_genre_id
                    WHERE e.to_genre_id IS NOT NULL
                      AND e.source <> :inferred_source
                      AND (from_region.genre_id IS NOT NULL OR to_region.genre_id IS NOT NULL)
                """),
                {"inferred_source": INFERRED_SOURCE},
            )
            or 0
        )
        subclass_rows = (
            (
                await conn.execute(
                    text("""
                SELECT
                    e.from_genre_id AS child_id,
                    child.wikipedia_title AS child_title,
                    e.to_genre_id AS parent_id,
                    parent.wikipedia_title AS parent_title,
                    parent.wikidata_qid AS parent_qid,
                    e.relation AS evidence_relation,
                    e.source AS evidence_source,
                    e.ordinal AS evidence_ordinal
                FROM wg_edges e
                JOIN wg_genres child ON child.id = e.from_genre_id
                JOIN wg_genres parent ON parent.id = e.to_genre_id
                LEFT JOIN wg_region_promoted_genres child_region ON child_region.genre_id = child.id
                LEFT JOIN wg_region_promoted_genres parent_region ON parent_region.genre_id = parent.id
                WHERE e.source = :source
                  AND e.relation = :relation
                  AND e.to_genre_id IS NOT NULL
                  AND child.deleted_at IS NULL
                  AND parent.deleted_at IS NULL
                  AND child.is_non_genre = false
                  AND parent.is_non_genre = false
                  AND child_region.genre_id IS NULL
                  AND parent_region.genre_id IS NULL
                ORDER BY parent.wikipedia_title, child.wikipedia_title
            """),
                    {"source": DIRECT_PARENT_SOURCE, "relation": DIRECT_PARENT_RELATION},
                )
            )
            .mappings()
            .fetchall()
        )

        reverse_rows = (
            (
                await conn.execute(
                    text("""
                SELECT
                    e.from_genre_id AS source_id,
                    source_g.wikipedia_title AS source_title,
                    e.to_genre_id AS target_id,
                    target_g.wikipedia_title AS target_title,
                    target_g.wikidata_qid AS target_qid,
                    source_g.summary AS source_summary,
                    e.relation AS evidence_relation,
                    e.source AS evidence_source,
                    e.ordinal AS evidence_ordinal
                FROM wg_edges e
                JOIN wg_genres source_g ON source_g.id = e.from_genre_id
                JOIN wg_genres target_g ON target_g.id = e.to_genre_id
                LEFT JOIN wg_region_promoted_genres source_region ON source_region.genre_id = source_g.id
                LEFT JOIN wg_region_promoted_genres target_region ON target_region.genre_id = target_g.id
                WHERE e.source <> :inferred_source
                  AND e.to_genre_id IS NOT NULL
                  AND source_g.deleted_at IS NULL
                  AND target_g.deleted_at IS NULL
                  AND source_g.is_non_genre = false
                  AND target_g.is_non_genre = false
                  AND source_region.genre_id IS NULL
                  AND target_region.genre_id IS NULL
                ORDER BY target_g.wikipedia_title, source_g.wikipedia_title
            """),
                    {"inferred_source": INFERRED_SOURCE},
                )
            )
            .mappings()
            .fetchall()
        )

        direct_rows = (
            await conn.execute(
                text("""
                SELECT e.from_genre_id, e.to_genre_id
                FROM wg_edges e
                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                LEFT JOIN wg_region_promoted_genres from_region ON from_region.genre_id = from_g.id
                LEFT JOIN wg_region_promoted_genres to_region ON to_region.genre_id = to_g.id
                WHERE e.to_genre_id IS NOT NULL
                  AND e.relation IN ('subgenre', 'derivative', 'fusion_genre')
                  AND e.source <> :inferred_source
                  AND from_g.deleted_at IS NULL
                  AND to_g.deleted_at IS NULL
                  AND from_g.is_non_genre = false
                  AND to_g.is_non_genre = false
                  AND from_region.genre_id IS NULL
                  AND to_region.genre_id IS NULL
            """),
                {"inferred_source": INFERRED_SOURCE},
            )
        ).fetchall()

        existing_edges = {
            (r.from_genre_id, r.relation, r.to_genre_id)
            for r in (
                await conn.execute(
                    text("""
                    SELECT from_genre_id, relation, to_genre_id
                    FROM wg_edges e
                    LEFT JOIN wg_region_promoted_genres from_region ON from_region.genre_id = e.from_genre_id
                    LEFT JOIN wg_region_promoted_genres to_region ON to_region.genre_id = e.to_genre_id
                    WHERE e.to_genre_id IS NOT NULL
                      AND e.source <> :inferred_source
                      AND from_region.genre_id IS NULL
                      AND to_region.genre_id IS NULL
                """),
                    {"inferred_source": INFERRED_SOURCE},
                )
            ).fetchall()
        }

    candidate_parent_child_rows = [
        (row["parent_id"], row["child_id"])
        for row in subclass_rows
        if row["parent_id"] != row["child_id"]
        and not _is_excluded_parent(row["parent_qid"], row["parent_title"])
    ]
    adjacency = _build_adjacency([(r[0], r[1]) for r in direct_rows] + candidate_parent_child_rows)
    existing_display_pairs = {
        (from_id, to_id)
        for from_id, relation, to_id in existing_edges
        if relation in DISPLAY_RELATIONS
    }
    inferred: list[InferredEdge] = []
    seen_candidates: set[tuple[str, str, str]] = set()
    stats.candidates = len(subclass_rows) + len(reverse_rows)

    for row in subclass_rows:
        parent_id = row["parent_id"]
        child_id = row["child_id"]
        parent_title = row["parent_title"]
        child_title = row["child_title"]

        if parent_id == child_id:
            stats.skipped_self_loop += 1
            continue

        if _is_excluded_parent(row["parent_qid"], parent_title):
            stats.skipped_excluded_parent += 1
            continue

        key = (parent_id, INFERRED_SUBGENRE_RELATION, child_id)
        if key in seen_candidates:
            stats.skipped_duplicate_candidate += 1
            continue
        seen_candidates.add(key)

        if key in existing_edges:
            stats.skipped_existing_direct += 1
            continue

        if _has_path(
            adjacency,
            parent_id,
            child_id,
            min_depth=2,
            max_depth=max_path_depth,
        ):
            seen_candidates.discard(key)
            stats.skipped_ancestor_shortcut += 1
            related_key = (parent_id, RELATED_RELATION, child_id)
            if related_key in existing_edges or related_key in seen_candidates:
                stats.skipped_existing_related += 1
                continue
            seen_candidates.add(related_key)
            edge = InferredEdge(
                parent_id=parent_id,
                parent_title=parent_title,
                child_id=child_id,
                child_title=child_title,
                relation=RELATED_RELATION,
                reason="ancestor shortcut from wikidata subclass_of",
                evidence_relation=row["evidence_relation"],
            )
            inferred.append(edge)
            stats.related_inserted += 1
            _add_sample(stats, edge, sample_size)
            continue

        edge = InferredEdge(
            parent_id=parent_id,
            parent_title=parent_title,
            child_id=child_id,
            child_title=child_title,
            relation=INFERRED_SUBGENRE_RELATION,
            reason="wikidata subclass_of direct-parent evidence",
            evidence_relation=row["evidence_relation"],
        )
        inferred.append(edge)
        stats.display_inserted += 1
        _add_sample(stats, edge, sample_size)

    for row in reverse_rows:
        source_id = row["source_id"]
        target_id = row["target_id"]
        source_title = row["source_title"]
        target_title = row["target_title"]
        evidence_relation = row["evidence_relation"]

        if source_id == target_id:
            stats.skipped_self_loop += 1
            continue

        if _is_excluded_parent(row["target_qid"], target_title):
            stats.skipped_excluded_parent += 1
            continue

        relation = _summary_supported_reverse_relation(
            row["source_summary"],
            source_title,
            target_title,
        ) or _reverse_coverage_relation(evidence_relation)
        key = (target_id, relation, source_id)

        if relation == RELATED_RELATION and (
            (target_id, source_id) in existing_display_pairs
            or any(
                edge.parent_id == target_id
                and edge.child_id == source_id
                and edge.relation in DISPLAY_RELATIONS
                for edge in inferred
            )
        ):
            stats.skipped_existing_related += 1
            continue

        if key in seen_candidates:
            stats.skipped_duplicate_candidate += 1
            continue

        if key in existing_edges:
            if relation == RELATED_RELATION:
                stats.skipped_existing_related += 1
            else:
                stats.skipped_existing_direct += 1
            continue

        if relation in DISPLAY_RELATIONS:
            removed_related = _remove_related_candidate_for_display(
                inferred,
                stats.sample,
                target_id,
                source_id,
            )
            stats.related_inserted -= removed_related
            reason = (
                "summary-confirmed reverse display edge from "
                f"{row['evidence_source']} {evidence_relation}"
            )
            evidence_relation = SUMMARY_EVIDENCE_RELATION
            stats.display_inserted += 1
        else:
            reason = f"reverse inbound coverage from {row['evidence_source']} {evidence_relation}"
            evidence_relation = _reverse_evidence_relation(evidence_relation)
            stats.related_inserted += 1

        seen_candidates.add(key)
        edge = InferredEdge(
            parent_id=target_id,
            parent_title=target_title,
            child_id=source_id,
            child_title=source_title,
            relation=relation,
            reason=reason,
            evidence_relation=evidence_relation,
        )
        inferred.append(edge)
        _add_sample(stats, edge, sample_size)

    if dry_run:
        stats.inserted = len(inferred)
        logger.info("inbound_index_dry_run", candidates=stats.candidates, inferred=len(inferred))
        return stats

    async with engine.begin() as conn:
        deleted = await conn.execute(
            text("DELETE FROM wg_edges WHERE source = :source"),
            {"source": INFERRED_SOURCE},
        )
        stats.deleted_existing = int(deleted.rowcount or 0)

        by_parent: dict[str, list[InferredEdge]] = defaultdict(list)
        for edge in inferred:
            by_parent[edge.parent_id].append(edge)

        for parent_id, edges in sorted(by_parent.items()):
            edges.sort(key=lambda e: e.child_title)
            for ordinal, edge in enumerate(edges):
                await conn.execute(
                    text("""
                        INSERT INTO wg_edges (
                            from_genre_id, to_genre_id, to_raw_label,
                            relation, source, ordinal, evidence_relation, first_seen_at
                        )
                        VALUES (
                            :from_id, :to_id, :raw_label,
                            :relation, :source, :ordinal, :evidence_relation, now()
                        )
                    """),
                    {
                        "from_id": parent_id,
                        "to_id": edge.child_id,
                        "raw_label": edge.child_title,
                        "relation": edge.relation,
                        "source": INFERRED_SOURCE,
                        "ordinal": ordinal,
                        "evidence_relation": edge.evidence_relation,
                    },
                )
                stats.inserted += 1

        await conn.execute(
            text("""
                INSERT INTO wg_snapshots (
                    id, kind, started_at, finished_at, nodes_total, edges_total, notes
                )
                SELECT
                    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                        || '-inbound-index',
                    'reconciler',
                    now(),
                    now(),
                    (SELECT count(*) FROM wg_genres
                     WHERE deleted_at IS NULL AND is_non_genre = false),
                    (
                        SELECT count(*)
                        FROM wg_edges e
                        JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                        LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                        WHERE from_g.deleted_at IS NULL
                          AND from_g.is_non_genre = false
                          AND (
                            e.to_genre_id IS NULL
                            OR (to_g.deleted_at IS NULL AND to_g.is_non_genre = false)
                          )
                    ),
                    :notes
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "notes": (
                    "Inbound relationship index. Derived high-confidence display edges "
                    "and non-display related_genre coverage edges."
                ),
            },
        )

    logger.info(
        "inbound_index_complete",
        candidates=stats.candidates,
        inserted=stats.inserted,
        deleted_existing=stats.deleted_existing,
    )
    return stats
