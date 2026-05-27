"""Detect and ignore circular display relationships.

The explorer has a synthetic "Music" root, backed by a curated list of broad
genres. This module walks outward from those same roots over graph-visible
child relations and marks any edge that would point back into the active DFS
path as ignored.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

import structlog
from sqlalchemy import text

from wiki_genres.curation import MANUAL_CURATION_EDGE_SOURCE, MANUAL_HIGH_LEVEL_ROOT_TITLES
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

LEGACY_DISPLAY_RELATIONS = ("subgenre", "derivative", "fusion_genre")
REVIEW_DISPLAY_RELATIONS = (
    "broader_genres",
    "subgenres",
    "derived_genres",
    "fusion_components",
    "fusion_descendants",
    "regional_variations",
)
DISPLAY_RELATIONS = (*REVIEW_DISPLAY_RELATIONS, *LEGACY_DISPLAY_RELATIONS)
RELATED_RELATION = "related_genre"
CYCLE_IGNORE_REASON = "cycle_guard: reachable display cycle"
SUMMARY_EVIDENCE_RELATION = "summary_subgenre_of"
HISTORICAL_ROOT_TITLES = (
    "Ancient music",
    "Prehistoric music",
    "Early music",
    "Medieval music",
    "Renaissance music",
    "Baroque music",
    "Classical period (music)",
    "Romantic music",
)
DEFAULT_ROOT_TITLES = (
    "Rock music",
    "Pop music",
    "Hip hop music",
    "Electronic music",
    "Jazz",
    "Classical music",
    "Rhythm and blues",
    "Country music",
    "Folk music",
    "Blues",
    "Heavy metal music",
    "Reggae",
    "World music",
    "Soundtrack",
    "Experimental music",
    *MANUAL_HIGH_LEVEL_ROOT_TITLES,
)


@dataclass(frozen=True)
class EdgeKey:
    from_genre_id: str
    relation: str
    source: str
    ordinal: int


@dataclass(frozen=True)
class TraversalEdge:
    key: EdgeKey
    to_genre_id: str
    from_title: str
    to_title: str
    evidence_relation: str | None = None

    @property
    def effective_relation(self) -> str:
        if self.key.relation == RELATED_RELATION and self.evidence_relation in DISPLAY_RELATIONS:
            return self.evidence_relation
        return self.key.relation

    @property
    def is_display_relationship(self) -> bool:
        return self.effective_relation in DISPLAY_RELATIONS


@dataclass
class IgnoredCycle:
    edge: TraversalEdge
    path_titles: list[str]


@dataclass
class CycleGuardStats:
    roots_requested: int = 0
    roots_found: int = 0
    roots_missing: list[str] = field(default_factory=list)
    music_country_roots_found: int = 0
    edges_scanned: int = 0
    nodes_visited: int = 0
    cleared_existing: int = 0
    ignored: int = 0
    sample: list[IgnoredCycle] = field(default_factory=list)
    dry_run: bool = False


def _build_adjacency(edges: list[TraversalEdge]) -> dict[str, list[TraversalEdge]]:
    adjacency: dict[str, list[TraversalEdge]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.key.from_genre_id].append(edge)
    return dict(adjacency)


def _edge_evidence_strength(edge: TraversalEdge) -> int:
    """Higher means this edge is better evidence and should survive cycles."""
    if edge.key.source == MANUAL_CURATION_EDGE_SOURCE:
        return -1
    if edge.evidence_relation == SUMMARY_EVIDENCE_RELATION:
        return 90
    if edge.key.source == "inbound_index" and edge.is_display_relationship:
        return 70
    if edge.key.source == "wikidata":
        return 62
    if edge.key.source == "infobox":
        return 55
    return 50


def _weakest_cycle_edge(edge: TraversalEdge, opposing_edges: list[TraversalEdge]) -> TraversalEdge:
    candidates = [edge, *opposing_edges]
    return min(
        candidates,
        key=lambda candidate: (
            _edge_evidence_strength(candidate),
            candidate.key.source == MANUAL_CURATION_EDGE_SOURCE,
        ),
    )


def find_cycle_edges(
    roots: list[str],
    traversal_adjacency: dict[str, list[TraversalEdge]],
    title_by_id: dict[str, str],
    *,
    check_adjacency: dict[str, list[TraversalEdge]] | None = None,
    sample_size: int = 25,
    ignored_edges_out: list[TraversalEdge] | None = None,
) -> tuple[list[EdgeKey], list[IgnoredCycle], int]:
    """Return edges that would close a cycle during root-outward traversal."""
    check_adjacency = check_adjacency or traversal_adjacency
    state: dict[str, Literal["visiting", "done"]] = {}
    stack: list[str] = []
    stack_index: dict[str, int] = {}
    ignored_keys: list[EdgeKey] = []
    ignored_seen: set[EdgeKey] = set()
    samples: list[IgnoredCycle] = []
    reachable_traversal_pairs: set[tuple[str, str]] = set()
    nodes_visited = 0
    opposing_display_edges: dict[tuple[str, str], list[TraversalEdge]] = defaultdict(list)
    for edges in check_adjacency.values():
        for edge in edges:
            if edge.is_display_relationship:
                opposing_display_edges[(edge.key.from_genre_id, edge.to_genre_id)].append(edge)

    def mark_cycle(edge: TraversalEdge, cycle_ids: list[str]) -> None:
        if edge.key.source == MANUAL_CURATION_EDGE_SOURCE:
            return
        if edge.key in ignored_seen:
            return
        ignored_seen.add(edge.key)
        ignored_keys.append(edge.key)
        if ignored_edges_out is not None:
            ignored_edges_out.append(edge)
        if len(samples) < sample_size:
            samples.append(
                IgnoredCycle(
                    edge=edge,
                    path_titles=[title_by_id.get(node, node) for node in cycle_ids],
                )
            )

    def dfs(node_id: str) -> None:
        nonlocal nodes_visited
        state[node_id] = "visiting"
        stack_index[node_id] = len(stack)
        stack.append(node_id)
        nodes_visited += 1

        for edge in check_adjacency.get(node_id, []):
            if state.get(edge.to_genre_id) == "visiting" and edge.is_display_relationship:
                cycle_ids = stack[stack_index[edge.to_genre_id] :] + [edge.to_genre_id]
                opposing_edges = []
                if len(cycle_ids) == 3:
                    opposing_edges = opposing_display_edges.get((edge.to_genre_id, node_id), [])
                mark_cycle(_weakest_cycle_edge(edge, opposing_edges), cycle_ids)

        for edge in traversal_adjacency.get(node_id, []):
            reachable_traversal_pairs.add((node_id, edge.to_genre_id))
            target_state = state.get(edge.to_genre_id)
            if target_state == "visiting":
                cycle_ids = stack[stack_index[edge.to_genre_id] :] + [edge.to_genre_id]
                opposing_edges = []
                if len(cycle_ids) == 3:
                    opposing_edges = opposing_display_edges.get((edge.to_genre_id, node_id), [])
                mark_cycle(_weakest_cycle_edge(edge, opposing_edges), cycle_ids)
                continue
            if target_state == "done":
                continue
            dfs(edge.to_genre_id)

        stack.pop()
        stack_index.pop(node_id, None)
        state[node_id] = "done"

    for root in roots:
        if state.get(root) is None:
            dfs(root)

    for checked_edges in check_adjacency.values():
        for edge in checked_edges:
            if not edge.is_display_relationship:
                continue
            if (edge.key.from_genre_id, edge.to_genre_id) not in reachable_traversal_pairs and (
                edge.to_genre_id,
                edge.key.from_genre_id,
            ) in reachable_traversal_pairs:
                opposing_edges = opposing_display_edges.get(
                    (edge.to_genre_id, edge.key.from_genre_id),
                    [],
                )
                chosen = _weakest_cycle_edge(edge, opposing_edges)
                mark_cycle(chosen, [edge.to_genre_id, edge.key.from_genre_id, edge.to_genre_id])

    return ignored_keys, samples, nodes_visited


async def _resolve_root_ids(
    conn: object,
    root_titles: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    direct_rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
            SELECT wikipedia_title, id
            FROM wg_genres
            WHERE wikipedia_title = ANY(:titles)
              AND deleted_at IS NULL
              AND is_non_genre = false
        """),
                {"titles": list(root_titles)},
            )
        )
        .mappings()
        .fetchall()
    )
    id_by_title = {row["wikipedia_title"]: row["id"] for row in direct_rows}

    missing_direct = [title for title in root_titles if title not in id_by_title]
    if missing_direct:
        redirect_rows = (
            (
                await conn.execute(  # type: ignore[attr-defined]
                    text("""
                SELECT r.from_title, r.to_genre_id
                FROM wg_redirects r
                JOIN wg_genres g ON g.id = r.to_genre_id
                WHERE r.from_title = ANY(:titles)
                  AND g.deleted_at IS NULL
                  AND g.is_non_genre = false
            """),
                    {"titles": missing_direct},
                )
            )
            .mappings()
            .fetchall()
        )
        for row in redirect_rows:
            id_by_title[row["from_title"]] = row["to_genre_id"]

    roots: list[str] = []
    missing: list[str] = []
    for title in root_titles:
        root_id = id_by_title.get(title)
        if root_id:
            roots.append(root_id)
        else:
            missing.append(title)
    return roots, missing


async def _resolve_music_country_root_ids(
    conn: object,
    *,
    exclude_ids: set[str],
) -> list[str]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
            SELECT id
            FROM wg_genres
            WHERE (
                id IN (
                    SELECT p.genre_id
                    FROM wg_region_promoted_genres p
                    JOIN wg_regions r ON r.id = p.region_id
                    WHERE r.kind = 'country'
                )
                OR (
                    id NOT IN (SELECT genre_id FROM wg_region_promoted_genres)
                    AND (
                        wikipedia_title ILIKE 'Traditional music of %'
                        OR wikipedia_title ILIKE 'Traditional % music'
                        OR wikipedia_title ILIKE '% traditional music'
                        OR wikipedia_title ILIKE 'Indigenous music%'
                        OR wikipedia_title ILIKE 'Indigenous % music'
                        OR wikipedia_title ILIKE 'Ancient % music'
                        OR wikipedia_title ILIKE 'Music in ancient %'
                        OR wikipedia_title ILIKE 'Music of ancient %'
                        OR wikipedia_title = ANY(:historical_titles)
                    )
                )
            )
              AND deleted_at IS NULL
              AND is_non_genre = false
              AND id <> ALL(:exclude_ids)
            ORDER BY wikipedia_title
        """),
                {
                    "exclude_ids": list(exclude_ids),
                    "historical_titles": list(HISTORICAL_ROOT_TITLES),
                },
            )
        )
        .mappings()
        .fetchall()
    )
    return [row["id"] for row in rows]


async def flag_circular_relationships(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
    reset_existing: bool = True,
    root_titles: tuple[str, ...] = DEFAULT_ROOT_TITLES,
) -> CycleGuardStats:
    """Mark graph-visible relationships that would make the Music tree cyclic."""
    await apply_migrations()
    engine = get_engine()
    stats = CycleGuardStats(
        roots_requested=len(root_titles),
        dry_run=dry_run,
    )

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
                {"reason": CYCLE_IGNORE_REASON},
            )
            stats.cleared_existing = int(result.rowcount or 0)
            result = await conn.execute(
                text("""
                    UPDATE wg_genre_relationships
                    SET is_ignored = false,
                        ignored_reason = NULL,
                        ignored_at = NULL
                    WHERE is_ignored = true
                      AND ignored_reason = :reason
                """),
                {"reason": CYCLE_IGNORE_REASON},
            )
            stats.cleared_existing += int(result.rowcount or 0)

        roots, missing = await _resolve_root_ids(conn, root_titles)
        hidden_roots = await _resolve_music_country_root_ids(
            conn,
            exclude_ids=set(roots),
        )
        roots = [*roots, *hidden_roots]
        stats.roots_found = len(roots)
        stats.roots_missing = missing
        stats.music_country_roots_found = len(hidden_roots)

        relation_order = {relation: i for i, relation in enumerate(DISPLAY_RELATIONS)}
        rows = (
            (
                await conn.execute(
                    text("""
                SELECT
                    e.from_genre_id,
                    e.to_genre_id,
                    e.relation,
                    e.evidence_relation,
                    e.source,
                    e.ordinal,
                    from_g.wikipedia_title AS from_title,
                    to_g.wikipedia_title AS to_title
                FROM wg_relationship_traversal_edges e
                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                WHERE e.to_genre_id IS NOT NULL
                  AND e.is_ignored = false
                  AND from_g.deleted_at IS NULL
                  AND from_g.is_non_genre = false
                  AND to_g.deleted_at IS NULL
                  AND to_g.is_non_genre = false
            """),
                )
            )
            .mappings()
            .fetchall()
        )

        edges = [
            TraversalEdge(
                key=EdgeKey(
                    from_genre_id=row["from_genre_id"],
                    relation=row["relation"],
                    source=row["source"],
                    ordinal=row["ordinal"],
                ),
                to_genre_id=row["to_genre_id"],
                from_title=row["from_title"],
                to_title=row["to_title"],
                evidence_relation=row["evidence_relation"],
            )
            for row in rows
        ]
        edges.sort(
            key=lambda edge: (
                edge.from_title.lower(),
                relation_order.get(edge.effective_relation, 99),
                edge.to_title.lower(),
                edge.key.source,
                edge.key.ordinal,
            )
        )
        stats.edges_scanned = len(edges)
        traversal_edges = [edge for edge in edges if edge.is_display_relationship]

        title_by_id: dict[str, str] = {}
        for edge in edges:
            title_by_id[edge.key.from_genre_id] = edge.from_title
            title_by_id[edge.to_genre_id] = edge.to_title

        ignored_edges: list[TraversalEdge] = []
        ignored_keys, samples, nodes_visited = find_cycle_edges(
            roots,
            _build_adjacency(traversal_edges),
            title_by_id,
            check_adjacency=_build_adjacency(edges),
            sample_size=sample_size,
            ignored_edges_out=ignored_edges,
        )
        stats.ignored = len(ignored_keys)
        stats.sample = samples
        stats.nodes_visited = nodes_visited

        if dry_run or not ignored_keys:
            logger.info(
                "cycle_guard_done",
                dry_run=dry_run,
                ignored=stats.ignored,
                nodes_visited=stats.nodes_visited,
            )
            return stats

        for key in ignored_keys:
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
                    "reason": CYCLE_IGNORE_REASON,
                    "from_id": key.from_genre_id,
                    "relation": key.relation,
                    "source": key.source,
                    "ordinal": key.ordinal,
                },
            )
        for edge in ignored_edges:
            await conn.execute(
                text("""
                    UPDATE wg_genre_relationships
                    SET is_ignored = true,
                        ignored_reason = :reason,
                        ignored_at = now()
                    WHERE relationship_type = :relation
                      AND source = :source
                      AND ordinal = :ordinal
                      AND status = 'active'
                      AND (
                        (
                          relationship_type in ('broader_genres', 'fusion_components', 'source_genres')
                          AND to_genre_id = :from_id
                          AND from_genre_id = :to_id
                        )
                        OR (
                          relationship_type not in ('broader_genres', 'fusion_components', 'source_genres')
                          AND from_genre_id = :from_id
                          AND to_genre_id = :to_id
                        )
                      )
                """),
                {
                    "reason": CYCLE_IGNORE_REASON,
                    "from_id": edge.key.from_genre_id,
                    "to_id": edge.to_genre_id,
                    "relation": edge.key.relation,
                    "source": edge.key.source,
                    "ordinal": edge.key.ordinal,
                },
            )

    logger.info(
        "cycle_guard_done",
        dry_run=dry_run,
        ignored=stats.ignored,
        nodes_visited=stats.nodes_visited,
    )
    return stats
