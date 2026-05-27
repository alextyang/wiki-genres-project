"""Timeline map endpoint."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from wiki_genres.api.models import (
    TimelineEdgeOut,
    TimelineNodeOut,
    TimelineResult,
    TimelineYearHintOut,
)
from wiki_genres.db import session_scope
from wiki_genres.loader.timeline_year_hints import YearHint, extract_year_hints
from wiki_genres.loader.semantic_cloud_layout import GENERAL_LAYOUT_KEY

router = APIRouter(prefix="/v1/timeline", tags=["timeline"])

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
ORIGIN_PARENT_RELATION = "origin_parent"
ORIGIN_PARENT_EVIDENCE_RELATIONS = ("stylistic_origin_of",)
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
RELATION_RANK = {
    "broader_genres": 0,
    "subgenres": 1,
    "subgenre": 1,
    "derived_genres": 2,
    "derivative": 2,
    "fusion_components": 3,
    "fusion_descendants": 3,
    "fusion_genre": 3,
    "regional_variations": 4,
    ORIGIN_PARENT_RELATION: 5,
}
DOWNWARD_CONNECTION_WEIGHT = 1.0
UPWARD_CONNECTION_WEIGHT = 0.35
LEFT_PAD = 120
TOP_PAD = 80
SEMANTIC_LANE_GAP = 76
DECADE_HEIGHT = 150
MIN_SEMANTIC_WIDTH = 190
NODE_ROW_HEIGHT = 44
NODE_COL_MIN_WIDTH = 132
NODE_COL_MAX_WIDTH = 300
DECADE_TOP_PAD = 46
DECADE_BOTTOM_PAD = 52
DECADE_EDGE_PAD = 34
LANE_WIDTH = 150
TIMELINE_HEIGHT = 1160
ROW_COLLISION_PX = 34
SEMANTIC_ROOT_ORDER = [
    "Classical music",
    "Folk music",
    "Country music",
    "Blues",
    "Jazz",
    "Rhythm and blues",
    "Rock music",
    "Pop music",
    "Hip hop music",
    "Electronic music",
    "Reggae",
    "World music",
    "Latin music",
    "Heavy metal music",
    "Experimental music",
    "Religious music",
    "Soundtrack",
]
SEMANTIC_ROOT_RANK = {root: index for index, root in enumerate(SEMANTIC_ROOT_ORDER)}


@dataclass(frozen=True)
class TimelineGraphEdge:
    from_genre_id: str
    to_genre_id: str
    relation: str
    source: str
    ordinal: int


@dataclass
class TimelineGraphNode:
    id: str
    title: str
    summary: str | None
    monthly_views_p30: int | None
    origins: list[str]
    categories: list[str]
    similarity_color: str | None = None
    root_affinity: dict[str, float] | None = None
    semantic_root: str | None = None
    depth: int = 0
    lane: int = 0
    x: float = 0
    y: float = 0
    inferred_year: int | None = None
    timeline_rank: float = 1
    timeline_importance: float = 0
    selected_distance: int | None = None
    selected_direction: str | None = None
    selected_connection_count: int | None = None
    selected_focus_score: float | None = None
    text_width: float | None = None
    text_height: float | None = None
    box_width: float | None = None
    box_height: float | None = None
    box_pad_x: float | None = None
    box_pad_y: float | None = None


@dataclass(frozen=True)
class TimelineGroupLayout:
    columns: int
    rows: int
    col_width: float
    width: float
    height: float


async def _get_complete_timeline(
    *,
    max_nodes: int,
    min_confidence: str,
    max_rank: float,
    selected_genre_id: str | None = None,
    include_routes: bool = False,
) -> TimelineResult:
    minimum = CONFIDENCE_RANK[min_confidence]
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text("""
                        SELECT
                            g.id,
                            g.wikipedia_title,
                            g.summary,
                            g.monthly_views_p30,
                            c.color_hex AS similarity_color,
                            c.root_affinity,
                            h.year_start,
                            h.year_end,
                            h.estimated_start,
                            h.estimated_end,
                            h.year_mean,
                            h.year_sd,
                            h.year_observation_count,
                            h.beginning_start,
                            h.beginning_end,
                            h.beginning_mean,
                            h.beginning_sd,
                            h.beginning_observation_count,
                            h.relevance_start,
                            h.relevance_end,
                            h.relevance_mean,
                            h.relevance_sd,
                            h.relevance_observation_count,
                            h.confidence,
                            h.year_kind,
                            h.source_type,
                            h.source_field,
                            h.evidence,
                            h.reason,
                            h.score,
                            layout.text_width,
                            layout.text_height,
                            layout.box_width,
                            layout.box_height,
                            layout.box_pad_x,
                            layout.box_pad_y
                        FROM wg_timeline_year_hints h
                        JOIN wg_genres g ON g.id = h.genre_id
                        LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                        LEFT JOIN wg_genre_semantic_layouts layout
                          ON layout.genre_id = g.id
                         AND layout.layout_key = :layout_key
                        WHERE h.has_hint = true
                          AND h.confidence = ANY(:allowed_confidences)
                          AND g.deleted_at IS NULL
                          AND g.is_non_genre = false
                        ORDER BY
                            h.year_start,
                            g.monthly_views_p30 DESC NULLS LAST,
                            g.wikipedia_title
                        LIMIT :max_nodes
                    """),
                    {
                        "allowed_confidences": [
                            confidence
                            for confidence, rank in CONFIDENCE_RANK.items()
                            if rank >= minimum
                        ],
                        "max_nodes": max_nodes,
                        "layout_key": GENERAL_LAYOUT_KEY,
                    },
                )
            )
            .mappings()
            .fetchall()
        )

    nodes_by_id: dict[str, TimelineGraphNode] = {}
    hints_by_id: dict[str, YearHint] = {}
    for row in rows:
        affinity = _root_affinity_dict(row["root_affinity"])
        node = TimelineGraphNode(
            id=row["id"],
            title=row["wikipedia_title"],
            summary=row["summary"],
            monthly_views_p30=row["monthly_views_p30"],
            origins=[],
            categories=[],
            similarity_color=row["similarity_color"],
            root_affinity=affinity,
            semantic_root=_semantic_root(affinity),
            text_width=row.get("text_width"),
            text_height=row.get("text_height"),
            box_width=row.get("box_width"),
            box_height=row.get("box_height"),
            box_pad_x=row.get("box_pad_x"),
            box_pad_y=row.get("box_pad_y"),
        )
        nodes_by_id[node.id] = node
        hints_by_id[node.id] = YearHint(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            year_start=row["year_start"],
            year_end=row["year_end"],
            estimated_start=row.get("estimated_start"),
            estimated_end=row.get("estimated_end"),
            year_mean=row.get("year_mean"),
            year_sd=row.get("year_sd"),
            year_observation_count=row.get("year_observation_count"),
            beginning_start=row.get("beginning_start"),
            beginning_end=row.get("beginning_end"),
            beginning_mean=row.get("beginning_mean"),
            beginning_sd=row.get("beginning_sd"),
            beginning_observation_count=row.get("beginning_observation_count"),
            relevance_start=row.get("relevance_start"),
            relevance_end=row.get("relevance_end"),
            relevance_mean=row.get("relevance_mean"),
            relevance_sd=row.get("relevance_sd"),
            relevance_observation_count=row.get("relevance_observation_count"),
            confidence=row["confidence"],
            year_kind=row["year_kind"],
            source_type=row["source_type"],
            source_field=row["source_field"],
            evidence=row["evidence"],
            reason=row["reason"],
            score=row["score"],
        )

    visible_edges = await _load_edges_for_nodes(set(nodes_by_id))
    nodes_by_id, hints_by_id, visible_edges = _filter_complete_vertical_relationships(
        nodes_by_id,
        hints_by_id,
        visible_edges,
    )
    _assign_timeline_importance(nodes_by_id, hints_by_id, visible_edges)
    _layout_complete_nodes(nodes_by_id, hints_by_id, visible_edges)
    visible_edges = [
        edge
        for edge in visible_edges
        if edge.from_genre_id in nodes_by_id and edge.to_genre_id in nodes_by_id
    ]
    selected_focus_ids = _apply_selected_focus(
        selected_genre_id=selected_genre_id,
        nodes=nodes_by_id,
        edges=visible_edges,
    )
    total_nodes = len(nodes_by_id)
    total_edges = len(visible_edges)
    keep_ids = {
        node.id
        for node in nodes_by_id.values()
        if node.timeline_rank <= max_rank
    }
    if selected_genre_id in nodes_by_id:
        keep_ids.add(selected_genre_id)
    keep_ids.update(selected_focus_ids)
    nodes_by_id = {
        node_id: node
        for node_id, node in nodes_by_id.items()
        if node_id in keep_ids
    }
    hints_by_id = {
        node_id: hint
        for node_id, hint in hints_by_id.items()
        if node_id in keep_ids
    }
    visible_edges = [
        edge
        for edge in visible_edges
        if edge.from_genre_id in nodes_by_id and edge.to_genre_id in nodes_by_id
    ]
    result_nodes = [
        _node_out(node, hints_by_id.get(node.id))
        for node in sorted(nodes_by_id.values(), key=lambda n: (n.y, n.x, n.title))
    ]
    result_edges = [_edge_out(edge, nodes_by_id, include_route=include_routes) for edge in visible_edges]
    dated_years = [hint.year_start for hint in hints_by_id.values()]
    return TimelineResult(
        root_id="__complete_timeline__",
        scope="all",
        min_confidence=min_confidence,
        year_min=min(dated_years) if dated_years else None,
        year_max=max(dated_years) if dated_years else None,
        nodes=result_nodes,
        edges=result_edges,
        stats={
            "nodes": len(result_nodes),
            "edges": len(result_edges),
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "dated_nodes": len(result_nodes),
            "inferred_nodes": 0,
        },
    )


def _filter_complete_vertical_relationships(
    nodes: dict[str, TimelineGraphNode],
    hints: dict[str, YearHint],
    edges: list[TimelineGraphEdge],
) -> tuple[dict[str, TimelineGraphNode], dict[str, YearHint], list[TimelineGraphEdge]]:
    vertical_node_ids: set[str] = set()
    vertical_edges: list[TimelineGraphEdge] = []
    for edge in edges:
        from_hint = hints.get(edge.from_genre_id)
        to_hint = hints.get(edge.to_genre_id)
        if from_hint is None or to_hint is None:
            continue
        if _timeline_row(from_hint.year_start) == _timeline_row(to_hint.year_start):
            continue
        vertical_node_ids.add(edge.from_genre_id)
        vertical_node_ids.add(edge.to_genre_id)
        vertical_edges.append(edge)

    return (
        {
            node_id: node
            for node_id, node in nodes.items()
            if node_id in vertical_node_ids
        },
        {
            node_id: hint
            for node_id, hint in hints.items()
            if node_id in vertical_node_ids
        },
        vertical_edges,
    )


def _timeline_row(year: int) -> int:
    return (year // 10) * 10


def _assign_timeline_importance(
    nodes: dict[str, TimelineGraphNode],
    hints: dict[str, YearHint],
    edges: list[TimelineGraphEdge],
) -> None:
    _, weighted_degree = _timeline_connection_scores(edges)

    scored: list[tuple[str, float, int, str]] = []
    for node in nodes.values():
        views = math.log10(max(0, node.monthly_views_p30 or 0) + 10)
        links = weighted_degree.get(node.id, 0)
        hint = hints.get(node.id)
        confidence_boost = 0.0
        if hint is not None:
            confidence_boost = {"high": 0.26, "medium": 0.1}.get(hint.confidence, 0.0)
        score = math.log2(links + 1) * 4.0 + views * 1.15 + confidence_boost
        scored.append((node.id, score, node.monthly_views_p30 or 0, node.title))

    scored.sort(key=lambda item: (-item[1], -item[2], item[3], item[0]))
    max_score = max((score for _, score, _, _ in scored), default=1)
    min_score = min((score for _, score, _, _ in scored), default=0)
    score_span = max(0.001, max_score - min_score)
    global_rank_by_id: dict[str, float] = {}
    global_span = max(1, len(scored) - 1)
    for index, (node_id, _, _, _) in enumerate(scored):
        global_rank_by_id[node_id] = index / global_span

    for node_id, score, _, _ in scored:
        node = nodes[node_id]
        node.timeline_importance = (score - min_score) / score_span

    scored_by_decade: dict[int, list[tuple[str, float, int, str]]] = defaultdict(list)
    for item in scored:
        node_id = item[0]
        hint = hints.get(node_id)
        if hint is None:
            continue
        scored_by_decade[_timeline_row(hint.year_start)].append(item)

    for decade_items in scored_by_decade.values():
        decade_span = max(1, len(decade_items) - 1)
        for index, (node_id, _, _, _) in enumerate(decade_items):
            decade_rank = index / decade_span
            global_rank = global_rank_by_id.get(node_id, 1)
            global_floor = global_rank * 0.34
            nodes[node_id].timeline_rank = max(min(decade_rank, global_rank), global_floor)


def _timeline_connection_scores(
    edges: list[TimelineGraphEdge],
) -> tuple[dict[str, int], dict[str, float]]:
    total_degree: dict[str, int] = defaultdict(int)
    weighted_degree: dict[str, float] = defaultdict(float)
    for edge in edges:
        total_degree[edge.from_genre_id] += 1
        total_degree[edge.to_genre_id] += 1
        weighted_degree[edge.from_genre_id] += DOWNWARD_CONNECTION_WEIGHT
        weighted_degree[edge.to_genre_id] += UPWARD_CONNECTION_WEIGHT
    return total_degree, weighted_degree


def _selected_focus_limit(depth: int) -> int | None:
    return {1: 12, 2: 8, 3: 4, 4: 2}.get(depth, 2)


def _selected_focus_total_limit(depth: int) -> int | None:
    return {1: 16, 2: 10, 3: 5, 4: 2}.get(depth, 2)


def _selected_focus_score(node: TimelineGraphNode, weighted_degree: float) -> float:
    views = math.log10(max(0, node.monthly_views_p30 or 0) + 10)
    return math.log2(weighted_degree + 1) * 4.0 + views * 1.2


def _selected_focus_sort_key(
    node_id: str,
    edge: TimelineGraphEdge,
    nodes: dict[str, TimelineGraphNode],
    weighted_degree: dict[str, float],
) -> tuple[float, int, float, str]:
    node = nodes[node_id]
    return (
        -_selected_focus_score(node, weighted_degree.get(node_id, 0)),
        RELATION_RANK.get(edge.relation, 99),
        node.timeline_rank,
        node.title,
    )


def _selected_focus_depth_sort_key(
    node_id: str,
    nodes: dict[str, TimelineGraphNode],
    weighted_degree: dict[str, float],
) -> tuple[float, float, str]:
    node = nodes[node_id]
    return (
        -_selected_focus_score(node, weighted_degree.get(node_id, 0)),
        node.timeline_rank,
        node.title,
    )


def _merge_selected_direction(current: str | None, direction: str) -> str:
    if current is None:
        return direction
    if current == direction or current == "selected":
        return current
    if direction == "selected":
        return current
    return "both"


def _apply_selected_focus(
    *,
    selected_genre_id: str | None,
    nodes: dict[str, TimelineGraphNode],
    edges: list[TimelineGraphEdge],
) -> set[str]:
    if not selected_genre_id or selected_genre_id not in nodes:
        return set()

    parent_edges: dict[str, list[TimelineGraphEdge]] = defaultdict(list)
    child_edges: dict[str, list[TimelineGraphEdge]] = defaultdict(list)
    degree, weighted_degree = _timeline_connection_scores(edges)
    for edge in edges:
        parent_edges[edge.to_genre_id].append(edge)
        child_edges[edge.from_genre_id].append(edge)

    focus: dict[str, tuple[int, str]] = {selected_genre_id: (0, "selected")}

    def walk(direction: str) -> None:
        frontier = {selected_genre_id}
        seen = {selected_genre_id}
        for depth in range(1, 5):
            candidates: dict[str, TimelineGraphEdge] = {}
            for node_id in frontier:
                incident = parent_edges.get(node_id, []) if direction == "up" else child_edges.get(node_id, [])
                for edge in incident:
                    next_id = edge.from_genre_id if direction == "up" else edge.to_genre_id
                    if next_id not in nodes or next_id in seen:
                        continue
                    current = candidates.get(next_id)
                    if current is None or _selected_focus_sort_key(next_id, edge, nodes, weighted_degree) < _selected_focus_sort_key(next_id, current, nodes, weighted_degree):
                        candidates[next_id] = edge

            ordered = sorted(
                candidates,
                key=lambda node_id: _selected_focus_sort_key(node_id, candidates[node_id], nodes, weighted_degree),
            )
            limit = _selected_focus_limit(depth)
            if limit is not None:
                ordered = ordered[:limit]
            if not ordered:
                break

            next_frontier: set[str] = set()
            for node_id in ordered:
                seen.add(node_id)
                next_frontier.add(node_id)
                current_distance, current_direction = focus.get(node_id, (depth, direction))
                focus[node_id] = (
                    min(current_distance, depth),
                    _merge_selected_direction(current_direction, direction),
                )
            frontier = next_frontier

    walk("up")
    walk("down")

    limited_focus: dict[str, tuple[int, str]] = {selected_genre_id: focus[selected_genre_id]}
    for depth in range(1, 5):
        depth_nodes = [
            node_id
            for node_id, (distance, _) in focus.items()
            if distance == depth
        ]
        depth_nodes.sort(key=lambda node_id: _selected_focus_depth_sort_key(node_id, nodes, weighted_degree))
        limit = _selected_focus_total_limit(depth)
        if limit is not None:
            depth_nodes = depth_nodes[:limit]
        for node_id in depth_nodes:
            limited_focus[node_id] = focus[node_id]
    focus = limited_focus

    focus_scores = {
        node_id: _selected_focus_score(nodes[node_id], weighted_degree.get(node_id, 0))
        for node_id in focus
    }
    max_focus_score = max(focus_scores.values(), default=1)
    min_focus_score = min(focus_scores.values(), default=0)
    score_span = max(0.001, max_focus_score - min_focus_score)

    for node_id, (distance, direction) in focus.items():
        node = nodes[node_id]
        normalized_score = (focus_scores[node_id] - min_focus_score) / score_span
        node.selected_distance = distance
        node.selected_direction = direction
        node.selected_connection_count = degree.get(node_id, 0)
        node.selected_focus_score = normalized_score
        focus_rank = min(0.14, max(0.001, 0.006 + distance * 0.014 - normalized_score * 0.008))
        node.timeline_rank = min(node.timeline_rank, focus_rank)
        node.timeline_importance = max(node.timeline_importance, max(0.42, 1 - distance * 0.14, normalized_score))

    return set(focus)


@router.get("", response_model=TimelineResult)
async def get_timeline(
    genre_id: str | None = Query(None, description="Optional selected genre id."),
    scope: Literal["all", "descendants", "around"] = Query(
        "all",
        description="Complete timeline, descendants only, or selected genre with parent context.",
    ),
    max_depth: int = Query(5, ge=1, le=8),
    max_nodes: int = Query(2200, ge=10, le=5000),
    max_rank: float = Query(1.0, ge=0.02, le=1.0),
    min_confidence: Literal["low", "medium", "high"] = Query("low"),
    selected_genre_id: str | None = Query(None),
    include_routes: bool = Query(False),
) -> TimelineResult:
    """Return a deterministic chronological layout for a selected genre family."""
    if scope == "all":
        return await _get_complete_timeline(
            max_nodes=max_nodes,
            min_confidence=min_confidence,
            max_rank=max_rank,
            selected_genre_id=selected_genre_id,
            include_routes=include_routes,
        )
    if genre_id is None:
        raise HTTPException(status_code=422, detail="genre_id is required outside scope=all.")
    async with session_scope() as session:
        root = (
            await session.execute(
                text("""
                    SELECT id
                    FROM wg_genres
                    WHERE id = :genre_id
                      AND deleted_at IS NULL
                      AND is_non_genre = false
                """),
                {"genre_id": genre_id},
            )
        ).first()
        if root is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        edge_rows = (
            (
                await session.execute(
                    text("""
                        SELECT
                            e.from_genre_id,
                            e.to_genre_id,
                            CASE
                              WHEN e.relation = :related_relation
                               AND e.evidence_relation = ANY(:display_relations)
                              THEN e.evidence_relation
                              WHEN e.relation = :related_relation
                               AND e.evidence_relation = ANY(:origin_parent_evidence_relations)
                              THEN :origin_parent_relation
                              ELSE e.relation
                            END AS relation,
                            e.source,
                            e.ordinal,
                            to_g.wikipedia_title AS to_title,
                            to_g.monthly_views_p30 AS to_monthly_views_p30
                        FROM wg_relationship_traversal_edges e
                        JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                        JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND (
                            e.relation = ANY(:display_relations)
                            OR (
                              e.relation = :related_relation
                              AND e.evidence_relation = ANY(:display_relations)
                            )
                            OR (
                              e.relation = :related_relation
                              AND e.evidence_relation = ANY(:origin_parent_evidence_relations)
                            )
                          )
                          AND from_g.deleted_at IS NULL
                          AND from_g.is_non_genre = false
                          AND to_g.deleted_at IS NULL
                          AND to_g.is_non_genre = false
                    """),
                    {
                        "display_relations": list(DISPLAY_RELATIONS),
                        "related_relation": RELATED_RELATION,
                        "origin_parent_relation": ORIGIN_PARENT_RELATION,
                        "origin_parent_evidence_relations": list(ORIGIN_PARENT_EVIDENCE_RELATIONS),
                    },
                )
            )
            .mappings()
            .fetchall()
        )

        trace_rows = []
        if scope == "around":
            trace_rows = (
                (
                    await session.execute(
                        text("""
                            SELECT
                                parent_genre_id,
                                parent_relation,
                                parent_source,
                                parent_ordinal,
                                path_genre_ids
                            FROM wg_music_reachable_parents
                            WHERE genre_id = :genre_id
                            ORDER BY
                                array_length(path_genre_ids, 1),
                                parent_depth_from_music,
                                parent_genre_id
                            LIMIT 18
                        """),
                        {"genre_id": genre_id},
                    )
                )
                .mappings()
                .fetchall()
            )

    adjacency: dict[str, list[TimelineGraphEdge]] = defaultdict(list)
    edge_by_pair: dict[tuple[str, str], TimelineGraphEdge] = {}
    for row in edge_rows:
        edge = TimelineGraphEdge(
            from_genre_id=row["from_genre_id"],
            to_genre_id=row["to_genre_id"],
            relation=row["relation"],
            source=row["source"],
            ordinal=row["ordinal"],
        )
        adjacency[edge.from_genre_id].append(edge)
        edge_by_pair.setdefault((edge.from_genre_id, edge.to_genre_id), edge)

    for children in adjacency.values():
        children.sort(
            key=lambda edge: (
                RELATION_RANK.get(edge.relation, 99),
                -(next(
                    (
                        row["to_monthly_views_p30"] or 0
                        for row in edge_rows
                        if row["to_genre_id"] == edge.to_genre_id
                    ),
                    0,
                )),
                edge.to_genre_id,
            )
        )

    node_depths, visible_edges = _walk_descendants(
        genre_id=genre_id,
        adjacency=adjacency,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    if scope == "around":
        _add_trace_context(
            genre_id=genre_id,
            trace_rows=trace_rows,
            node_depths=node_depths,
            visible_edges=visible_edges,
            edge_by_pair=edge_by_pair,
            max_nodes=max_nodes,
        )

    nodes_by_id = await _load_nodes(set(node_depths))
    for node_id, depth in node_depths.items():
        if node_id in nodes_by_id:
            nodes_by_id[node_id].depth = depth

    visible_edges = [
        edge
        for edge in visible_edges
        if edge.from_genre_id in nodes_by_id and edge.to_genre_id in nodes_by_id
    ]

    persisted_hints = await _load_persisted_hints(set(nodes_by_id), min_confidence=min_confidence)
    hints_by_id = {}
    for node_id, node in nodes_by_id.items():
        if node_id in persisted_hints:
            hints_by_id[node_id] = persisted_hints[node_id]
            continue
        hints_by_id[node_id] = _best_hint(
            extract_year_hints(
                genre_id=node.id,
                title=node.title,
                summary=node.summary,
                origins=node.origins,
                categories=node.categories,
            ),
            min_confidence=min_confidence,
        )

    _layout_nodes(nodes_by_id, visible_edges, hints_by_id)
    result_nodes = [
        _node_out(node, hints_by_id.get(node.id))
        for node in sorted(nodes_by_id.values(), key=lambda n: (n.x, n.lane, n.title))
    ]
    result_edges = [_edge_out(edge, nodes_by_id) for edge in visible_edges]

    dated_years = [
        hint.year_start
        for hint in hints_by_id.values()
        if hint is not None
    ]
    return TimelineResult(
        root_id=genre_id,
        scope=scope,
        min_confidence=min_confidence,
        year_min=min(dated_years) if dated_years else None,
        year_max=max(dated_years) if dated_years else None,
        nodes=result_nodes,
        edges=result_edges,
        stats={
            "nodes": len(result_nodes),
            "edges": len(result_edges),
            "dated_nodes": len(dated_years),
            "inferred_nodes": sum(1 for node in nodes_by_id.values() if node.inferred_year),
        },
    )


def _walk_descendants(
    *,
    genre_id: str,
    adjacency: dict[str, list[TimelineGraphEdge]],
    max_depth: int,
    max_nodes: int,
) -> tuple[dict[str, int], list[TimelineGraphEdge]]:
    depths = {genre_id: 0}
    visible_edges: list[TimelineGraphEdge] = []
    queue = deque([genre_id])

    while queue and len(depths) < max_nodes:
        parent_id = queue.popleft()
        parent_depth = depths[parent_id]
        if parent_depth >= max_depth:
            continue
        for edge in adjacency.get(parent_id, []):
            if len(depths) >= max_nodes:
                break
            child_depth = parent_depth + 1
            if edge.to_genre_id not in depths:
                depths[edge.to_genre_id] = child_depth
                queue.append(edge.to_genre_id)
            else:
                depths[edge.to_genre_id] = min(depths[edge.to_genre_id], child_depth)
            visible_edges.append(edge)

    return depths, visible_edges


def _add_trace_context(
    *,
    genre_id: str,
    trace_rows,
    node_depths: dict[str, int],
    visible_edges: list[TimelineGraphEdge],
    edge_by_pair: dict[tuple[str, str], TimelineGraphEdge],
    max_nodes: int,
) -> None:
    seen_edges = {(edge.from_genre_id, edge.to_genre_id) for edge in visible_edges}
    for row in trace_rows:
        path = list(row["path_genre_ids"] or [])
        if not path:
            continue
        if path[-1] != row["parent_genre_id"]:
            path.append(row["parent_genre_id"])
        if path[-1] != genre_id:
            path.append(genre_id)

        for depth, node_id in enumerate(path):
            if len(node_depths) >= max_nodes and node_id not in node_depths:
                break
            node_depths[node_id] = min(node_depths.get(node_id, depth), depth)

        for index, from_id in enumerate(path[:-1]):
            to_id = path[index + 1]
            if (from_id, to_id) in seen_edges:
                continue
            edge = edge_by_pair.get((from_id, to_id))
            if edge is None and to_id == genre_id:
                edge = TimelineGraphEdge(
                    from_genre_id=from_id,
                    to_genre_id=to_id,
                    relation=row["parent_relation"],
                    source=row["parent_source"],
                    ordinal=row["parent_ordinal"],
                )
            if edge is not None:
                visible_edges.append(edge)
                seen_edges.add((from_id, to_id))


async def _load_nodes(node_ids: set[str]) -> dict[str, TimelineGraphNode]:
    if not node_ids:
        return {}
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text("""
                        SELECT
                            g.id,
                            g.wikipedia_title,
                            g.summary,
                            g.monthly_views_p30,
                            layout.text_width,
                            layout.text_height,
                            layout.box_width,
                            layout.box_height,
                            layout.box_pad_x,
                            layout.box_pad_y,
                            COALESCE(
                                array_agg(DISTINCT o.value)
                                    FILTER (WHERE o.value IS NOT NULL),
                                '{}'
                            ) AS origins,
                            COALESCE(
                                array_agg(DISTINCT c.category)
                                    FILTER (WHERE c.category IS NOT NULL),
                                '{}'
                            ) AS categories
                        FROM wg_genres g
                        LEFT JOIN wg_origins o ON o.genre_id = g.id
                        LEFT JOIN wg_categories c ON c.genre_id = g.id
                        LEFT JOIN wg_genre_semantic_layouts layout
                          ON layout.genre_id = g.id
                         AND layout.layout_key = :layout_key
                        WHERE g.id = ANY(:node_ids)
                          AND g.deleted_at IS NULL
                          AND g.is_non_genre = false
                        GROUP BY
                            g.id,
                            g.wikipedia_title,
                            g.summary,
                            g.monthly_views_p30,
                            layout.text_width,
                            layout.text_height,
                            layout.box_width,
                            layout.box_height,
                            layout.box_pad_x,
                            layout.box_pad_y
                    """),
                    {"node_ids": list(node_ids), "layout_key": GENERAL_LAYOUT_KEY},
                )
            )
            .mappings()
            .fetchall()
        )

    return {
        row["id"]: TimelineGraphNode(
            id=row["id"],
            title=row["wikipedia_title"],
            summary=row["summary"],
            monthly_views_p30=row["monthly_views_p30"],
            origins=list(row["origins"] or []),
            categories=list(row["categories"] or []),
            text_width=row.get("text_width"),
            text_height=row.get("text_height"),
            box_width=row.get("box_width"),
            box_height=row.get("box_height"),
            box_pad_x=row.get("box_pad_x"),
            box_pad_y=row.get("box_pad_y"),
        )
        for row in rows
    }


async def _load_edges_for_nodes(node_ids: set[str]) -> list[TimelineGraphEdge]:
    if not node_ids:
        return []
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text("""
                        SELECT
                            e.from_genre_id,
                            e.to_genre_id,
                            CASE
                              WHEN e.relation = :related_relation
                               AND e.evidence_relation = ANY(:display_relations)
                              THEN e.evidence_relation
                              WHEN e.relation = :related_relation
                               AND e.evidence_relation = ANY(:origin_parent_evidence_relations)
                              THEN :origin_parent_relation
                              ELSE e.relation
                            END AS relation,
                            e.source,
                            e.ordinal
                        FROM wg_relationship_traversal_edges e
                        WHERE e.from_genre_id = ANY(:node_ids)
                          AND e.to_genre_id = ANY(:node_ids)
                          AND e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND (
                            e.relation = ANY(:display_relations)
                            OR (
                              e.relation = :related_relation
                              AND e.evidence_relation = ANY(:display_relations)
                            )
                            OR (
                              e.relation = :related_relation
                              AND e.evidence_relation = ANY(:origin_parent_evidence_relations)
                            )
                          )
                    """),
                    {
                        "node_ids": list(node_ids),
                        "display_relations": list(DISPLAY_RELATIONS),
                        "related_relation": RELATED_RELATION,
                        "origin_parent_relation": ORIGIN_PARENT_RELATION,
                        "origin_parent_evidence_relations": list(ORIGIN_PARENT_EVIDENCE_RELATIONS),
                    },
                )
            )
            .mappings()
            .fetchall()
        )
    return [
        TimelineGraphEdge(
            from_genre_id=row["from_genre_id"],
            to_genre_id=row["to_genre_id"],
            relation=row["relation"],
            source=row["source"],
            ordinal=row["ordinal"],
        )
        for row in rows
    ]


async def _load_persisted_hints(
    node_ids: set[str],
    *,
    min_confidence: str,
) -> dict[str, YearHint | None]:
    if not node_ids:
        return {}
    minimum = CONFIDENCE_RANK[min_confidence]
    try:
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                            SELECT
                                h.genre_id,
                                g.wikipedia_title,
                                h.has_hint,
                                h.year_start,
                                h.year_end,
                                h.estimated_start,
                                h.estimated_end,
                                h.year_mean,
                                h.year_sd,
                                h.year_observation_count,
                                h.beginning_start,
                                h.beginning_end,
                                h.beginning_mean,
                                h.beginning_sd,
                                h.beginning_observation_count,
                                h.relevance_start,
                                h.relevance_end,
                                h.relevance_mean,
                                h.relevance_sd,
                                h.relevance_observation_count,
                                h.confidence,
                                h.year_kind,
                                h.source_type,
                                h.source_field,
                                h.evidence,
                                h.reason,
                                h.score
                            FROM wg_timeline_year_hints h
                            JOIN wg_genres g ON g.id = h.genre_id
                            WHERE h.genre_id = ANY(:node_ids)
                        """),
                        {"node_ids": list(node_ids)},
                    )
                )
                .mappings()
                .fetchall()
            )
    except Exception:  # noqa: BLE001
        return {}

    hints: dict[str, YearHint | None] = {}
    for row in rows:
        if not row["has_hint"]:
            hints[row["genre_id"]] = None
            continue
        if CONFIDENCE_RANK.get(row["confidence"], 0) < minimum:
            hints[row["genre_id"]] = None
            continue
        hints[row["genre_id"]] = YearHint(
            genre_id=row["genre_id"],
            title=row["wikipedia_title"],
            year_start=row["year_start"],
            year_end=row["year_end"],
            estimated_start=row.get("estimated_start"),
            estimated_end=row.get("estimated_end"),
            year_mean=row.get("year_mean"),
            year_sd=row.get("year_sd"),
            year_observation_count=row.get("year_observation_count"),
            beginning_start=row.get("beginning_start"),
            beginning_end=row.get("beginning_end"),
            beginning_mean=row.get("beginning_mean"),
            beginning_sd=row.get("beginning_sd"),
            beginning_observation_count=row.get("beginning_observation_count"),
            relevance_start=row.get("relevance_start"),
            relevance_end=row.get("relevance_end"),
            relevance_mean=row.get("relevance_mean"),
            relevance_sd=row.get("relevance_sd"),
            relevance_observation_count=row.get("relevance_observation_count"),
            confidence=row["confidence"],
            year_kind=row["year_kind"],
            source_type=row["source_type"],
            source_field=row["source_field"],
            evidence=row["evidence"],
            reason=row["reason"],
            score=row["score"],
        )
    return hints


def _best_hint(hints: list[YearHint], *, min_confidence: str) -> YearHint | None:
    minimum = CONFIDENCE_RANK[min_confidence]
    for hint in hints:
        if CONFIDENCE_RANK.get(hint.confidence, 0) >= minimum:
            return hint
    return None


def _layout_nodes(
    nodes: dict[str, TimelineGraphNode],
    edges: list[TimelineGraphEdge],
    hints: dict[str, YearHint | None],
) -> None:
    if not nodes:
        return

    parent_edges: dict[str, list[TimelineGraphEdge]] = defaultdict(list)
    child_edges: dict[str, list[TimelineGraphEdge]] = defaultdict(list)
    for edge in edges:
        parent_edges[edge.to_genre_id].append(edge)
        child_edges[edge.from_genre_id].append(edge)

    dated_years = [hint.year_start for hint in hints.values() if hint is not None]
    if dated_years:
        min_year = min(dated_years)
        max_year = max(max(dated_years), min_year + 20)
    else:
        min_year = 1900
        max_year = 2000

    for node in sorted(nodes.values(), key=lambda item: item.depth):
        hint = hints.get(node.id)
        if hint is not None:
            node.inferred_year = None
            continue

        parent_years = [
            _node_year(nodes[edge.from_genre_id], hints.get(edge.from_genre_id))
            for edge in parent_edges.get(node.id, [])
            if edge.from_genre_id in nodes
        ]
        parent_years = [year for year in parent_years if year is not None]
        if parent_years:
            node.inferred_year = max(parent_years) + 8
        else:
            node.inferred_year = min_year + node.depth * 12

    all_years = [
        _node_year(node, hints.get(node.id))
        for node in nodes.values()
        if _node_year(node, hints.get(node.id)) is not None
    ]
    min_year = min(all_years) if all_years else min_year
    max_year = max(max(all_years), min_year + 20) if all_years else max_year

    lane_slots: dict[tuple[int, int], int] = {}
    ordered_nodes = sorted(
        nodes.values(),
        key=lambda node: (
            _node_year(node, hints.get(node.id)) or min_year,
            node.depth,
            -(node.monthly_views_p30 or 0),
            node.title,
        ),
    )
    for node in ordered_nodes:
        year = _node_year(node, hints.get(node.id)) or min_year
        bucket = round((year - min_year) / 5)
        parent_lanes = [
            nodes[edge.from_genre_id].lane
            for edge in parent_edges.get(node.id, [])
            if edge.from_genre_id in nodes
        ]
        ideal_lane = round(sum(parent_lanes) / len(parent_lanes)) if parent_lanes else node.depth
        lane = _nearest_free_lane(bucket, ideal_lane, lane_slots)
        lane_slots[(bucket, lane)] = 1
        node.lane = lane
        node.x = LEFT_PAD + lane * LANE_WIDTH
        node.y = TOP_PAD + ((year - min_year) / max(1, max_year - min_year)) * TIMELINE_HEIGHT

    _relax_lanes(nodes, edges)
    _resolve_lane_collisions(nodes)


def _layout_complete_nodes(
    nodes: dict[str, TimelineGraphNode],
    hints: dict[str, YearHint],
    edges: list[TimelineGraphEdge],
) -> None:
    if not nodes:
        return
    decades = sorted({(hint.year_start // 10) * 10 for hint in hints.values()})
    decade_groups: dict[int, list[TimelineGraphNode]] = defaultdict(list)

    for node in nodes.values():
        decade_groups[_timeline_row(hints[node.id].year_start)].append(node)

    ordered_layers = _decross_timeline_layers(
        decade_groups=decade_groups,
        decades=decades,
        hints=hints,
        edges=edges,
    )

    group_layouts: dict[int, TimelineGroupLayout] = {
        decade: _packed_group_layout(ordered_layers[decade])
        for decade in decades
    }
    timeline_width = max(
        (layout.width for layout in group_layouts.values()),
        default=MIN_SEMANTIC_WIDTH,
    )

    decade_heights: dict[int, float] = {}
    for decade in decades:
        decade_heights[decade] = max(
            DECADE_HEIGHT,
            DECADE_TOP_PAD + group_layouts[decade].height + DECADE_BOTTOM_PAD + DECADE_EDGE_PAD,
        )

    decade_top: dict[int, float] = {}
    y_cursor = TOP_PAD
    for decade in decades:
        decade_top[decade] = y_cursor
        y_cursor += decade_heights[decade]

    for decade in decades:
        group = ordered_layers[decade]
        layout = group_layouts[decade]
        group_left = LEFT_PAD + (timeline_width - layout.width) / 2
        group_top = decade_top[decade] + DECADE_TOP_PAD
        for index, node in enumerate(group):
            hint = hints[node.id]
            column = index % layout.columns
            row = index // layout.columns
            year_offset = _year_micro_offset(hint.year_start, decade, layout.rows)
            affinity_offset = _secondary_affinity_offset(node.root_affinity or {}, layout.col_width)
            node.lane = column
            node.x = (
                group_left
                + column * layout.col_width
                + layout.col_width / 2
                + affinity_offset
            )
            node.y = group_top + row * NODE_ROW_HEIGHT + NODE_ROW_HEIGHT / 2 + year_offset


def _decross_timeline_layers(
    *,
    decade_groups: dict[int, list[TimelineGraphNode]],
    decades: list[int],
    hints: dict[str, YearHint],
    edges: list[TimelineGraphEdge],
) -> dict[int, list[TimelineGraphNode]]:
    layers = {
        decade: sorted(
            decade_groups[decade],
            key=lambda node: (
                SEMANTIC_ROOT_RANK.get(node.semantic_root or "Other", len(SEMANTIC_ROOT_ORDER)),
                _timeline_row(hints[node.id].year_start),
                -(node.monthly_views_p30 or 0),
                node.title,
            ),
        )
        for decade in decades
    }
    node_decade = {
        node.id: decade
        for decade, layer in layers.items()
        for node in layer
    }
    incident: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.from_genre_id not in node_decade or edge.to_genre_id not in node_decade:
            continue
        incident[edge.from_genre_id].append(edge.to_genre_id)
        incident[edge.to_genre_id].append(edge.from_genre_id)

    order_maps = _timeline_order_maps(layers)
    semantic_span = max(1, len(SEMANTIC_ROOT_ORDER) - 1)
    for _ in range(8):
        for ordered_decades in (decades, list(reversed(decades))):
            for decade in ordered_decades:
                layer = layers[decade]
                layer_size = max(1, len(layer) - 1)

                def sort_key(
                    node: TimelineGraphNode,
                    *,
                    active_decade: int = decade,
                    active_layer_size: int = layer_size,
                ) -> tuple[float, int, int, str]:
                    neighbor_scores = []
                    for neighbor_id in incident.get(node.id, []):
                        neighbor_decade = node_decade.get(neighbor_id)
                        if neighbor_decade is None or neighbor_decade == active_decade:
                            continue
                        distance = max(1, abs(neighbor_decade - active_decade) // 10)
                        neighbor_order = order_maps.get(neighbor_decade, {}).get(neighbor_id)
                        if neighbor_order is None:
                            continue
                        neighbor_scores.append((neighbor_order, 1 / distance))
                    current_order = order_maps.get(active_decade, {}).get(node.id, 0)
                    if neighbor_scores:
                        weighted_sum = sum(order * weight for order, weight in neighbor_scores)
                        weight_total = sum(weight for _, weight in neighbor_scores)
                        barycenter = weighted_sum / max(weight_total, 0.001)
                    else:
                        barycenter = current_order
                    root_rank = SEMANTIC_ROOT_RANK.get(
                        node.semantic_root or "Other",
                        len(SEMANTIC_ROOT_ORDER),
                    )
                    semantic_anchor = (root_rank / semantic_span) * active_layer_size
                    blended = barycenter * 0.76 + semantic_anchor * 0.24
                    return (
                        blended,
                        root_rank,
                        -(node.monthly_views_p30 or 0),
                        node.title,
                    )

                layers[decade] = sorted(layer, key=sort_key)
                order_maps[decade] = {
                    node.id: index
                    for index, node in enumerate(layers[decade])
                }
    return layers


def _timeline_order_maps(
    layers: dict[int, list[TimelineGraphNode]],
) -> dict[int, dict[str, int]]:
    return {
        decade: {
            node.id: index
            for index, node in enumerate(layer)
        }
        for decade, layer in layers.items()
    }


def _packed_group_layout(group: list[TimelineGraphNode]) -> TimelineGroupLayout:
    count = max(1, len(group))
    columns = max(1, math.ceil(math.sqrt(count * 1.45)))
    rows = math.ceil(count / columns)
    if count >= 36 and rows < 5:
        rows = 5
        columns = math.ceil(count / rows)
    max_label_width = max(
        (_estimated_node_width(node) for node in group),
        default=NODE_COL_MIN_WIDTH,
    )
    col_width = min(NODE_COL_MAX_WIDTH, max(NODE_COL_MIN_WIDTH, max_label_width + 24))
    return TimelineGroupLayout(
        columns=columns,
        rows=rows,
        col_width=col_width,
        width=columns * col_width,
        height=rows * NODE_ROW_HEIGHT,
    )


def _estimated_node_width(node: TimelineGraphNode) -> float:
    label = _display_label(node.title)
    if node.text_width is not None:
        return min(NODE_COL_MAX_WIDTH - 24, max(88, float(node.text_width) * (15 / 13) + 28))
    return min(NODE_COL_MAX_WIDTH - 24, max(88, len(label) * 7.6 + 34))


def _year_micro_offset(year: int, decade: int, rows: int) -> float:
    if rows <= 1:
        return 0
    centered_year = (year - decade) - 4.5
    return max(-2, min(2, centered_year * 0.45))


def _nearest_free_lane(
    bucket: int,
    ideal_lane: int,
    lane_slots: dict[tuple[int, int], int],
) -> int:
    for offset in range(0, 80):
        candidates = [ideal_lane] if offset == 0 else [ideal_lane + offset, ideal_lane - offset]
        for candidate in candidates:
            if candidate < 0:
                continue
            if (bucket, candidate) not in lane_slots:
                return candidate
    return ideal_lane


def _relax_lanes(nodes: dict[str, TimelineGraphNode], edges: list[TimelineGraphEdge]) -> None:
    for _ in range(2):
        for edge in sorted(edges, key=lambda item: nodes[item.to_genre_id].x):
            parent = nodes.get(edge.from_genre_id)
            child = nodes.get(edge.to_genre_id)
            if not parent or not child:
                continue
            if abs(parent.lane - child.lane) <= 3:
                continue
            child.lane = round((child.lane * 2 + parent.lane) / 3)
            child.x = LEFT_PAD + child.lane * LANE_WIDTH


def _resolve_lane_collisions(nodes: dict[str, TimelineGraphNode]) -> None:
    occupied: set[tuple[int, int]] = set()
    for node in sorted(nodes.values(), key=lambda item: (item.y, item.lane, item.title)):
        bucket = round(node.y / ROW_COLLISION_PX)
        lane = _nearest_free_lane(bucket, node.lane, dict.fromkeys(occupied, 1))
        occupied.add((bucket, lane))
        node.lane = lane
        node.x = LEFT_PAD + lane * LANE_WIDTH


def _node_year(node: TimelineGraphNode, hint: YearHint | None) -> int | None:
    if hint is not None:
        return hint.year_start
    return node.inferred_year


def _node_out(node: TimelineGraphNode, hint: YearHint | None) -> TimelineNodeOut:
    return TimelineNodeOut(
        id=node.id,
        wikipedia_title=node.title,
        label=_display_label(node.title),
        depth=node.depth,
        lane=node.lane,
        x=round(node.x, 2),
        y=round(node.y, 2),
        year_start=hint.year_start if hint else node.inferred_year,
        year_end=hint.year_end if hint else None,
        year_confidence=hint.confidence if hint else None,
        year_kind=hint.year_kind if hint else None,
        is_inferred_year=hint is None,
        monthly_views_p30=node.monthly_views_p30,
        similarity_color=node.similarity_color,
        semantic_root=node.semantic_root,
        timeline_rank=round(node.timeline_rank, 6),
        timeline_importance=round(node.timeline_importance, 6),
        selected_distance=node.selected_distance,
        selected_direction=node.selected_direction,
        selected_connection_count=node.selected_connection_count,
        selected_focus_score=round(node.selected_focus_score, 6) if node.selected_focus_score is not None else None,
        text_width=node.text_width,
        text_height=node.text_height,
        box_width=node.box_width,
        box_height=node.box_height,
        box_pad_x=node.box_pad_x,
        box_pad_y=node.box_pad_y,
        hint=_hint_out(hint) if hint else None,
    )


def _hint_out(hint: YearHint) -> TimelineYearHintOut:
    return TimelineYearHintOut(
        year_start=hint.year_start,
        year_end=hint.year_end,
        estimated_start=hint.estimated_start,
        estimated_end=hint.estimated_end,
        year_mean=hint.year_mean,
        year_sd=hint.year_sd,
        year_observation_count=hint.year_observation_count,
        beginning_start=hint.beginning_start,
        beginning_end=hint.beginning_end,
        beginning_mean=hint.beginning_mean,
        beginning_sd=hint.beginning_sd,
        beginning_observation_count=hint.beginning_observation_count,
        relevance_start=hint.relevance_start,
        relevance_end=hint.relevance_end,
        relevance_mean=hint.relevance_mean,
        relevance_sd=hint.relevance_sd,
        relevance_observation_count=hint.relevance_observation_count,
        confidence=hint.confidence,
        year_kind=hint.year_kind,
        source_type=hint.source_type,
        source_field=hint.source_field,
        evidence=hint.evidence,
        reason=hint.reason,
        score=hint.score,
    )


def _edge_out(
    edge: TimelineGraphEdge,
    nodes: dict[str, TimelineGraphNode],
    *,
    include_route: bool = True,
) -> TimelineEdgeOut:
    route: list[list[float]] = []
    if not include_route:
        return TimelineEdgeOut(
            from_genre_id=edge.from_genre_id,
            to_genre_id=edge.to_genre_id,
            relation=edge.relation,
            source=edge.source,
            route=route,
        )
    start = nodes[edge.from_genre_id]
    end = nodes[edge.to_genre_id]
    port_offset = 22
    start_y = start.y + port_offset
    end_y = end.y - port_offset
    control_gap = max(36, abs(end_y - start_y) * 0.42)
    direction = 1 if end_y >= start_y else -1
    route = [
        [round(start.x, 2), round(start_y, 2)],
        [round(start.x, 2), round(start_y + control_gap * direction, 2)],
        [round(end.x, 2), round(end_y - control_gap * direction, 2)],
        [round(end.x, 2), round(end_y, 2)],
    ]
    return TimelineEdgeOut(
        from_genre_id=edge.from_genre_id,
        to_genre_id=edge.to_genre_id,
        relation=edge.relation,
        source=edge.source,
        route=route,
    )


def _stable_channel(*parts: str) -> int:
    value = 0
    for part in parts:
        for char in part:
            value = (value * 33 + ord(char)) % 9973
    return value % 9


def _display_label(title: str) -> str:
    return (
        title.replace(" music genre", "")
        .replace(" (music)", "")
        .replace(" (genre)", "")
        .removesuffix(" music")
    )


def _root_affinity_dict(value) -> dict[str, float]:  # noqa: ANN001
    if isinstance(value, dict):
        return {
            str(key): float(val)
            for key, val in value.items()
            if isinstance(val, int | float) and val > 0
        }
    return {}


def _semantic_root(affinity: dict[str, float]) -> str:
    if not affinity:
        return "Other"
    return max(
        affinity,
        key=lambda root: (
            affinity[root],
            -SEMANTIC_ROOT_RANK.get(root, len(SEMANTIC_ROOT_ORDER)),
            root,
        ),
    )


def _secondary_affinity_offset(affinity: dict[str, float], width: float) -> float:
    if len(affinity) < 2:
        return 0
    ranked = sorted(
        affinity,
        key=lambda root: (
            affinity[root],
            -SEMANTIC_ROOT_RANK.get(root, len(SEMANTIC_ROOT_ORDER)),
            root,
        ),
        reverse=True,
    )
    secondary = ranked[1]
    rank = SEMANTIC_ROOT_RANK.get(secondary, len(SEMANTIC_ROOT_ORDER) / 2)
    normalized = (rank / max(1, len(SEMANTIC_ROOT_ORDER) - 1)) - 0.5
    return normalized * min(72, width * 0.18)
