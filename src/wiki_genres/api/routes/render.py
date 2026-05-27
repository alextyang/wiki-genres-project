"""Progressive viewport render streams for explorer modes."""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator, Iterable
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from wiki_genres.api.routes.genres import (
    _cloud_anchor_rank,
    _cloud_selected_relationship_tier,
    get_genre_cloud,
)
from wiki_genres.api.routes.timeline import get_timeline

router = APIRouter(prefix="/v1/render", tags=["render"])

_STREAM_MEDIA_TYPE = "application/x-ndjson"
_STREAM_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}

_MIN_VIEW_SCALE = 0.12
_TIMELINE_RENDER_RANK_EPSILON = 0.024
_TIMELINE_NODE_OVERLAP_PAD_PX = 8
_TIMELINE_PLACEMENT_MAX_SCREEN_OFFSET = 180
_TIMELINE_EXTRA_EDGE_MAX = 8
_TIMELINE_NON_CORE_SIDE_EDGE_LIMIT = 1
_RELATION_RANK = {
    "broader_genres": 0,
    "subgenres": 1,
    "subgenre": 0,
    "derived_genres": 2,
    "derivative": 1,
    "fusion_components": 3,
    "fusion_descendants": 3,
    "fusion_genre": 2,
    "regional_variations": 4,
    "origin_parent": 5,
}


def _line(packet: dict[str, Any]) -> str:
    return json.dumps(jsonable_encoder(packet), separators=(",", ":")) + "\n"


def _timeline_bounds(nodes: Iterable[dict[str, Any]]) -> dict[str, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for node in nodes:
        x = node.get("x")
        y = node.get("y")
        if isinstance(x, int | float) and isinstance(y, int | float):
            xs.append(float(x))
            ys.append(float(y))
    if not xs or not ys:
        return None
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
    }


def _timeline_node_sort_key(node: dict[str, Any], selected_genre_id: str | None) -> tuple[float, float, str]:
    selected_rank = 0.0 if selected_genre_id and node.get("id") == selected_genre_id else 1.0
    focus_distance = node.get("selected_distance")
    distance_rank = float(focus_distance) if isinstance(focus_distance, int | float) else 99.0
    rank = node.get("timeline_rank")
    return (
        selected_rank,
        distance_rank,
        float(rank) if isinstance(rank, int | float) else 1.0,
        str(node.get("wikipedia_title") or node.get("label") or ""),
    )


def _display_label(value: object) -> str:
    return (
        str(value or "")
        .replace(" music genre", "")
        .replace(" (music)", "")
        .replace(" (genre)", "")
        .removesuffix(" music")
    )


def _timeline_detail_for_scale(scale: float) -> float:
    low_zoom_detail = max(0.0, min(0.45, ((scale - _MIN_VIEW_SCALE) / 0.60) * 0.45))
    if scale <= 0.72:
        return low_zoom_detail
    return max(0.0, min(1.0, 0.45 + ((scale - 0.72) / 2.28) * 0.55))


def _timeline_visible_rank_cutoff(detail: float) -> float:
    return 0.018 + detail * 0.36


def _timeline_core_rank_cutoff() -> float:
    return _timeline_visible_rank_cutoff(_timeline_detail_for_scale(_MIN_VIEW_SCALE))


def _timeline_focus_distance_cutoff(detail: float, *, scale: float, focus_active: bool) -> int:
    base = int(1 + detail * 4.2)
    if not focus_active:
        return max(1, min(4, base))
    boosted = int(2 + max(0.0, scale - 0.18) * 15)
    tolerant = int(max(base, boosted) + (1 if scale <= 0.26 else 0))
    return max(1, min(4, tolerant))


def _timeline_selected_background_rank_cutoff(detail: float, *, scale: float, focus_active: bool) -> float:
    base = _timeline_visible_rank_cutoff(detail)
    if not focus_active or scale < 0.18:
        return base
    t = max(0.0, min(1.0, (scale - 0.18) / 0.18))
    return max(base, 0.05 + t * 0.06)


def _edge_key(edge: dict[str, Any]) -> str:
    return f"{edge.get('from_genre_id')}->{edge.get('to_genre_id')}:{edge.get('relation') or ''}:{edge.get('source') or ''}"


def _build_timeline_visibility(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    node_ranks: dict[str, float] = {}
    node_scores: dict[str, float] = {}
    node_widths: dict[str, float] = {}
    edge_ranks: dict[str, float] = {}
    edges_by_node: dict[str, list[dict[str, Any]]] = {}
    focus_node_ids: set[str] = set()
    focus_distances: dict[str, float] = {}
    focus_scores: dict[str, float] = {}

    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        selected_distance = node.get("selected_distance")
        focus_score = 0.0
        if isinstance(selected_distance, int | float):
            focus_node_ids.add(node_id)
            focus_distances[node_id] = float(selected_distance)
            focus_score = max(0.0, min(1.0, float(node.get("selected_focus_score") or 0)))
            focus_scores[node_id] = focus_score
        focus_rank = (
            1.0
            if not isinstance(selected_distance, int | float)
            else min(0.14, max(0.001, 0.006 + float(selected_distance) * 0.014 - focus_score * 0.008))
        )
        raw_rank = node.get("timeline_rank")
        node_ranks[node_id] = min(float(raw_rank) if isinstance(raw_rank, int | float) else 1.0, focus_rank)
        raw_score = node.get("timeline_importance")
        node_scores[node_id] = float(raw_score) if isinstance(raw_score, int | float) else 0.0
        label = _display_label(node.get("label") or node.get("wikipedia_title"))
        node_widths[node_id] = max(72.0, min(230.0, len(label) * 7.5 + 28.0))

    for edge in edges:
        from_id = str(edge.get("from_genre_id") or "")
        to_id = str(edge.get("to_genre_id") or "")
        if not from_id or not to_id:
            continue
        relation = edge.get("relation")
        relation_boost = (
            -0.04
            if relation in {"broader_genres", "subgenres", "subgenre"}
            else 0.02
            if relation in {"derived_genres", "derivative"}
            else 0.06
        )
        edge_ranks[_edge_key(edge)] = max(node_ranks.get(from_id, 1.0), node_ranks.get(to_id, 1.0)) + relation_boost
        edges_by_node.setdefault(from_id, []).append(edge)
        edges_by_node.setdefault(to_id, []).append(edge)

    return {
        "node_ranks": node_ranks,
        "node_scores": node_scores,
        "node_widths": node_widths,
        "edge_ranks": edge_ranks,
        "edges_by_node": edges_by_node,
        "focus_node_ids": focus_node_ids,
        "focus_distances": focus_distances,
        "focus_scores": focus_scores,
    }


def _timeline_node_render_scale(node_id: str, visibility: dict[str, Any], *, focus_active: bool) -> float:
    importance = max(0.0, min(1.0, visibility["node_scores"].get(node_id, 0.0)))
    focus_score = max(0.0, min(1.0, visibility["focus_scores"].get(node_id, 0.0)))
    focus_boost = focus_score * 0.12 if focus_active and node_id in visibility["focus_node_ids"] else 0.0
    return 1 + importance * 0.1 + focus_boost


def _timeline_world_bounds(
    node: dict[str, Any],
    x: float,
    y: float,
    *,
    scale: float,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> dict[str, float]:
    node_id = str(node.get("id") or "")
    node_scale = _timeline_node_render_scale(node_id, visibility, focus_active=focus_active)
    width = (visibility["node_widths"].get(node_id, 120.0) * node_scale) / max(0.001, scale)
    height = (36.0 * node_scale) / max(0.001, scale)
    pad = _TIMELINE_NODE_OVERLAP_PAD_PX / max(0.001, scale)
    if focus_active and node_id not in visibility["focus_node_ids"] and node_id != selected_genre_id:
        pad *= 1.35
    return {
        "left": x - width / 2 - pad,
        "right": x + width / 2 + pad,
        "top": y - height / 2 - pad,
        "bottom": y + height / 2 + pad,
    }


def _bounds_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    return a["left"] < b["right"] and a["right"] > b["left"] and a["top"] < b["bottom"] and a["bottom"] > b["top"]


def _timeline_placement_offsets() -> list[dict[str, float]]:
    values = [{"dx": 0.0, "dy": 0.0, "distance": 0.0}]
    directions = [
        (1, 0), (-1, 0),
        (0, 1), (0, -1),
        (1, 0.52), (-1, 0.52),
        (1, -0.52), (-1, -0.52),
        (0.55, 1), (-0.55, 1),
        (0.55, -1), (-0.55, -1),
    ]
    for step in [34, 58, 88, 122, 160, _TIMELINE_PLACEMENT_MAX_SCREEN_OFFSET]:
        for dx, dy in directions:
            values.append({"dx": dx * step, "dy": dy * step, "distance": step * math.hypot(dx, dy)})
    return values


_TIMELINE_PLACEMENT_OFFSETS = _timeline_placement_offsets()


def _placement_in_viewport(bounds: dict[str, float], viewport: dict[str, float] | None) -> bool:
    if viewport is None:
        return True
    return (
        bounds["right"] >= viewport["left"]
        and bounds["left"] <= viewport["right"]
        and bounds["bottom"] >= viewport["top"]
        and bounds["top"] <= viewport["bottom"]
    )


def _timeline_placement_candidate(
    node: dict[str, Any],
    x: float,
    y: float,
    kept_bounds: list[dict[str, float]],
    *,
    viewport: dict[str, float] | None,
    scale: float,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> dict[str, Any] | None:
    bounds = _timeline_world_bounds(
        node,
        x,
        y,
        scale=scale,
        visibility=visibility,
        focus_active=focus_active,
        selected_genre_id=selected_genre_id,
    )
    if not _placement_in_viewport(bounds, viewport):
        return None
    if any(_bounds_overlap(bounds, existing) for existing in kept_bounds):
        return None
    return {"x": x, "y": y, "bounds": bounds}


def _timeline_place_node(
    node: dict[str, Any],
    kept_bounds: list[dict[str, float]],
    *,
    viewport: dict[str, float] | None,
    scale: float,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> dict[str, Any] | None:
    origin_x = float(node.get("x") or 0)
    origin_y = float(node.get("y") or 0)
    best: dict[str, Any] | None = None
    for offset in _TIMELINE_PLACEMENT_OFFSETS:
        x = origin_x + offset["dx"] / max(0.001, scale)
        y = origin_y + offset["dy"] / max(0.001, scale)
        candidate = _timeline_placement_candidate(
            node,
            x,
            y,
            kept_bounds,
            viewport=viewport,
            scale=scale,
            visibility=visibility,
            focus_active=focus_active,
            selected_genre_id=selected_genre_id,
        )
        if candidate is None:
            continue
        score = offset["distance"] + abs(offset["dy"]) * 1.45
        if best is None or score < best["score"]:
            best = {**candidate, "score": score}
    return best


def _timeline_node_priority(
    node: dict[str, Any],
    *,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> tuple[float, float, str, str]:
    node_id = str(node.get("id") or "")
    if node_id == selected_genre_id:
        priority = -2.0
    elif focus_active and node_id in visibility["focus_node_ids"]:
        distance = visibility["focus_distances"].get(node_id, 4.0)
        score = visibility["focus_scores"].get(node_id, 0.0)
        priority = -1.5 + distance * 0.05 - score * 0.08
    else:
        priority = visibility["node_ranks"].get(node_id, 1.0) - visibility["node_scores"].get(node_id, 0.0) * 0.035
    return (
        priority,
        float(node.get("y") or 0),
        str(node.get("label") or node.get("wikipedia_title") or ""),
        node_id,
    )


def _timeline_cull_overlapping_nodes(
    candidates: list[dict[str, Any]],
    *,
    viewport: dict[str, float] | None,
    scale: float,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda node: _timeline_node_priority(
            node,
            visibility=visibility,
            focus_active=focus_active,
            selected_genre_id=selected_genre_id,
        ),
    )
    kept: list[dict[str, Any]] = []
    kept_bounds: list[dict[str, float]] = []
    for node in ordered:
        static_x = float(node.get("x") or 0)
        static_y = float(node.get("y") or 0)
        placement = (
            _timeline_placement_candidate(
                node,
                static_x,
                static_y,
                kept_bounds,
                viewport=viewport,
                scale=scale,
                visibility=visibility,
                focus_active=focus_active,
                selected_genre_id=selected_genre_id,
            )
            if focus_active
            else _timeline_place_node(
                node,
                kept_bounds,
                viewport=viewport,
                scale=scale,
                visibility=visibility,
                focus_active=focus_active,
                selected_genre_id=selected_genre_id,
            )
        )
        if placement is None and node.get("id") != selected_genre_id:
            continue
        render_x = float(placement["x"]) if placement else static_x
        render_y = float(placement["y"]) if placement else static_y
        placed = {**node, "renderX": round(render_x, 2), "renderY": round(render_y, 2)}
        kept.append(placed)
        kept_bounds.append(
            placement["bounds"] if placement else _timeline_world_bounds(
                placed,
                render_x,
                render_y,
                scale=scale,
                visibility=visibility,
                focus_active=focus_active,
                selected_genre_id=selected_genre_id,
            )
        )
    return sorted(kept, key=lambda node: (float(node.get("renderY") or node.get("y") or 0), float(node.get("renderX") or node.get("x") or 0)))


def _timeline_edge_priority(edge: dict[str, Any], visibility: dict[str, Any]) -> tuple[float, str]:
    return (
        visibility["edge_ranks"].get(_edge_key(edge), 1.0) * 10 + _RELATION_RANK.get(str(edge.get("relation") or ""), 9),
        _edge_key(edge),
    )


def _timeline_has_alternate_path(
    from_id: str,
    to_id: str,
    skip_key: str,
    adjacency: dict[str, list[dict[str, Any]]],
) -> bool:
    queue: list[tuple[str, int]] = [(from_id, 0)]
    seen = {from_id}
    while queue:
        current, depth = queue.pop(0)
        if depth >= 5:
            continue
        for edge in adjacency.get(current, []):
            key = _edge_key(edge)
            if key == skip_key:
                continue
            edge_to = str(edge.get("to_genre_id") or "")
            if edge_to == to_id:
                return True
            if edge_to in seen:
                continue
            seen.add(edge_to)
            queue.append((edge_to, depth + 1))
    return False


def _timeline_extra_edge_allowance(node_id: str, candidate_degree: dict[str, int], node_by_id: dict[str, dict[str, Any]]) -> int:
    node = node_by_id.get(node_id) or {}
    views = max(0.0, float(node.get("monthly_views_p30") or 0))
    degree = candidate_degree.get(node_id, 0)
    if degree <= 2:
        return 0
    view_factor = max(0.18, min(1.35, math.log10(views + 10) / 3.35))
    connection_factor = math.sqrt(max(0, degree - 2))
    return max(0, min(_TIMELINE_EXTRA_EDGE_MAX, round(connection_factor * view_factor)))


def _timeline_node_is_core(
    node_id: str,
    *,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> bool:
    if node_id == selected_genre_id:
        return True
    if focus_active and node_id in visibility["focus_node_ids"]:
        return True
    return visibility["node_ranks"].get(node_id, 1.0) <= _timeline_core_rank_cutoff()


def _timeline_edge_side(node_id: str, edge: dict[str, Any], positions: dict[str, dict[str, float]]) -> str:
    self_pos = positions.get(node_id)
    other_id = str(edge.get("to_genre_id") if edge.get("from_genre_id") == node_id else edge.get("from_genre_id"))
    other_pos = positions.get(other_id)
    if self_pos is None or other_pos is None:
        return "bottom" if edge.get("from_genre_id") == node_id else "top"
    return "top" if other_pos["y"] < self_pos["y"] else "bottom"


def _timeline_side_limit(
    node_id: str,
    node_by_id: dict[str, dict[str, Any]],
    *,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
) -> float:
    if node_id == selected_genre_id:
        return math.inf
    if focus_active and node_id in visibility["focus_node_ids"]:
        distance = visibility["focus_distances"].get(node_id, 4)
        if distance <= 1:
            return math.inf
        if distance == 2:
            return 10
        if distance == 3:
            return 5
    if not _timeline_node_is_core(
        node_id,
        visibility=visibility,
        focus_active=focus_active,
        selected_genre_id=selected_genre_id,
    ):
        return _TIMELINE_NON_CORE_SIDE_EDGE_LIMIT
    views = max(0.0, float((node_by_id.get(node_id) or {}).get("monthly_views_p30") or 0))
    return max(2, min(7, round(math.log10(views + 10) * 1.8)))


def _timeline_trim_edge_sides(
    candidates: list[dict[str, Any]],
    rendered_node_ids: set[str],
    node_by_id: dict[str, dict[str, Any]],
    fallback_candidates: list[dict[str, Any]],
    *,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
    positions: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    result_keys: set[str] = set()
    side_usage: dict[str, int] = {}
    incident_counts = {node_id: 0 for node_id in rendered_node_ids}

    def can_use(edge: dict[str, Any]) -> bool:
        for node_id in [str(edge.get("from_genre_id") or ""), str(edge.get("to_genre_id") or "")]:
            side = _timeline_edge_side(node_id, edge, positions)
            key = f"{node_id}:{side}"
            limit = _timeline_side_limit(
                node_id,
                node_by_id,
                visibility=visibility,
                focus_active=focus_active,
                selected_genre_id=selected_genre_id,
            )
            if side_usage.get(key, 0) >= limit:
                return False
        return True

    def record(edge: dict[str, Any]) -> None:
        for node_id in [str(edge.get("from_genre_id") or ""), str(edge.get("to_genre_id") or "")]:
            side = _timeline_edge_side(node_id, edge, positions)
            key = f"{node_id}:{side}"
            side_usage[key] = side_usage.get(key, 0) + 1
            incident_counts[node_id] = incident_counts.get(node_id, 0) + 1

    for edge in candidates:
        if not can_use(edge):
            continue
        result.append(edge)
        result_keys.add(_edge_key(edge))
        record(edge)

    for node_id in rendered_node_ids:
        if incident_counts.get(node_id, 0) > 0:
            continue
        edge = next(
            (
                candidate
                for candidate in fallback_candidates
                if _edge_key(candidate) not in result_keys
                and (candidate.get("from_genre_id") == node_id or candidate.get("to_genre_id") == node_id)
            ),
            None,
        )
        if edge is None:
            continue
        result.append(edge)
        result_keys.add(_edge_key(edge))
        record(edge)
    return result


def _timeline_consolidated_edges(
    edges: list[dict[str, Any]],
    rendered_node_ids: set[str],
    edge_endpoint_node_ids: set[str],
    edge_rank_cutoff: float,
    node_by_id: dict[str, dict[str, Any]],
    *,
    visibility: dict[str, Any],
    focus_active: bool,
    selected_genre_id: str | None,
    positions: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    fallback_by_pair: dict[str, dict[str, Any]] = {}
    best_by_pair: dict[str, dict[str, Any]] = {}
    for edge in edges:
        from_id = str(edge.get("from_genre_id") or "")
        to_id = str(edge.get("to_genre_id") or "")
        if from_id not in rendered_node_ids and to_id not in rendered_node_ids:
            continue
        if from_id not in edge_endpoint_node_ids or to_id not in edge_endpoint_node_ids:
            continue
        pair_key = f"{from_id}->{to_id}"
        if pair_key not in fallback_by_pair or _timeline_edge_priority(edge, visibility) < _timeline_edge_priority(fallback_by_pair[pair_key], visibility):
            fallback_by_pair[pair_key] = edge
        if visibility["edge_ranks"].get(_edge_key(edge), 1.0) > edge_rank_cutoff:
            continue
        if pair_key not in best_by_pair or _timeline_edge_priority(edge, visibility) < _timeline_edge_priority(best_by_pair[pair_key], visibility):
            best_by_pair[pair_key] = edge

    candidates = sorted(best_by_pair.values(), key=lambda edge: _timeline_edge_priority(edge, visibility))
    candidate_degree: dict[str, int] = {}
    for edge in candidates:
        for node_id in [str(edge.get("from_genre_id") or ""), str(edge.get("to_genre_id") or "")]:
            candidate_degree[node_id] = candidate_degree.get(node_id, 0) + 1
    extra_allowance = {
        node_id: _timeline_extra_edge_allowance(node_id, candidate_degree, node_by_id)
        for node_id in rendered_node_ids
    }
    extra_usage: dict[str, int] = {}
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in candidates:
        adjacency.setdefault(str(edge.get("from_genre_id") or ""), []).append(edge)

    result: list[dict[str, Any]] = []
    for edge in candidates:
        from_id = str(edge.get("from_genre_id") or "")
        to_id = str(edge.get("to_genre_id") or "")
        if not _timeline_has_alternate_path(from_id, to_id, _edge_key(edge), adjacency):
            result.append(edge)
            continue
        from_used = extra_usage.get(from_id, 0)
        to_used = extra_usage.get(to_id, 0)
        if from_used >= extra_allowance.get(from_id, 0) and to_used >= extra_allowance.get(to_id, 0):
            continue
        extra_usage[from_id] = from_used + 1
        extra_usage[to_id] = to_used + 1
        result.append(edge)

    fallback_candidates = sorted(fallback_by_pair.values(), key=lambda edge: _timeline_edge_priority(edge, visibility))
    return _timeline_trim_edge_sides(
        result,
        rendered_node_ids,
        node_by_id,
        fallback_candidates,
        visibility=visibility,
        focus_active=focus_active,
        selected_genre_id=selected_genre_id,
        positions=positions,
    )


def _edge_path(from_id: str, to_id: str, positions: dict[str, dict[str, float]]) -> str:
    start = positions.get(from_id)
    end = positions.get(to_id)
    if start is None or end is None:
        return ""
    start_y = start["y"]
    end_y = end["y"]
    direction = 1 if end_y >= start_y else -1
    control_gap = max(34.0, abs(end_y - start_y) * 0.42)
    return (
        f"M {start['x']} {start_y} "
        f"C {start['x']} {start_y + control_gap * direction} "
        f"{end['x']} {end_y - control_gap * direction} "
        f"{end['x']} {end_y}"
    )


def _timeline_render_signature(render_cutoff: float, viewport: dict[str, float] | None) -> str:
    if viewport is None:
        return f"rank:{round(render_cutoff / _TIMELINE_RENDER_RANK_EPSILON)}|x:initial|y:initial"
    tile = 520
    return "|".join([
        f"rank:{round(render_cutoff / _TIMELINE_RENDER_RANK_EPSILON)}",
        f"x:{math.floor(viewport['left'] / tile)}:{math.ceil(viewport['right'] / tile)}",
        f"y:{math.floor(viewport['top'] / tile)}:{math.ceil(viewport['bottom'] / tile)}",
    ])


def _prepare_timeline_scene(
    data: dict[str, Any],
    *,
    selected_genre_id: str | None,
    scale: float,
    viewport: dict[str, float] | None,
) -> dict[str, Any]:
    nodes = list(data.get("nodes") or [])
    edges = list(data.get("edges") or [])
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id") is not None}
    visibility = _build_timeline_visibility(nodes, edges)
    focus_active = bool(selected_genre_id and selected_genre_id in visibility["focus_node_ids"])
    detail = _timeline_detail_for_scale(scale)
    render_cutoff = _timeline_visible_rank_cutoff(detail)
    background_cutoff = _timeline_selected_background_rank_cutoff(detail, scale=scale, focus_active=focus_active)
    focus_distance_cutoff = _timeline_focus_distance_cutoff(detail, scale=scale, focus_active=focus_active)

    render_candidates: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        rank = visibility["node_ranks"].get(node_id, 1.0)
        if focus_active and node_id in visibility["focus_node_ids"]:
            if visibility["focus_distances"].get(node_id, 99) > focus_distance_cutoff and node_id != selected_genre_id:
                continue
        elif node_id != selected_genre_id:
            cutoff = background_cutoff if focus_active else render_cutoff
            if rank > cutoff:
                continue
        render_candidates.append(node)

    rendered_nodes = _timeline_cull_overlapping_nodes(
        render_candidates,
        viewport=viewport,
        scale=scale,
        visibility=visibility,
        focus_active=focus_active,
        selected_genre_id=selected_genre_id,
    )
    rendered_node_ids = {str(node.get("id")) for node in rendered_nodes if node.get("id") is not None}
    positions = {
        str(node.get("id")): {"x": float(node.get("renderX") or node.get("x") or 0), "y": float(node.get("renderY") or node.get("y") or 0)}
        for node in rendered_nodes
        if node.get("id") is not None
    }
    positions.update({
        node_id: {"x": float(node.get("x") or 0), "y": float(node.get("y") or 0)}
        for node_id, node in node_by_id.items()
        if node_id not in positions
    })

    edge_rank_cutoff = 1.05 if focus_active else 0.10 + detail * 0.34
    edge_endpoint_node_ids = (
        {node_id for node_id in visibility["focus_node_ids"] if node_id in node_by_id}
        if focus_active
        else {
            str(node.get("id"))
            for node in nodes
            if node.get("id") == selected_genre_id or visibility["node_ranks"].get(str(node.get("id")), 1.0) <= render_cutoff
        }
    )
    candidate_edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for node_id in rendered_node_ids:
        for edge in visibility["edges_by_node"].get(node_id, []):
            key = _edge_key(edge)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            candidate_edges.append(edge)
    consolidated_edges = _timeline_consolidated_edges(
        candidate_edges,
        rendered_node_ids,
        edge_endpoint_node_ids,
        edge_rank_cutoff,
        node_by_id,
        visibility=visibility,
        focus_active=focus_active,
        selected_genre_id=selected_genre_id,
        positions=positions,
    )
    if focus_active:
        consolidated_edges = [
            edge
            for edge in consolidated_edges
            if edge.get("from_genre_id") in rendered_node_ids
            and edge.get("to_genre_id") in rendered_node_ids
            and (
                edge.get("from_genre_id") in visibility["focus_node_ids"]
                or edge.get("to_genre_id") in visibility["focus_node_ids"]
            )
        ]

    connected_node_ids: set[str] = set()
    for edge in consolidated_edges:
        connected_node_ids.add(str(edge.get("from_genre_id") or ""))
        connected_node_ids.add(str(edge.get("to_genre_id") or ""))
    final_nodes = rendered_nodes if focus_active or not consolidated_edges else [
        node for node in rendered_nodes if str(node.get("id") or "") in connected_node_ids
    ]
    final_node_ids = {str(node.get("id")) for node in final_nodes if node.get("id") is not None}
    final_positions = {
        str(node.get("id")): {"x": float(node.get("renderX") or node.get("x") or 0), "y": float(node.get("renderY") or node.get("y") or 0)}
        for node in final_nodes
        if node.get("id") is not None
    }
    rendered_edges = [
        {
            **edge,
            "key": _edge_key(edge),
            "path": _edge_path(str(edge.get("from_genre_id") or ""), str(edge.get("to_genre_id") or ""), final_positions),
        }
        for edge in consolidated_edges
        if edge.get("from_genre_id") in final_node_ids and edge.get("to_genre_id") in final_node_ids
    ]
    label_rank_cutoff = 0.18 + detail * 0.44
    scene_nodes = []
    for node in final_nodes:
        node_id = str(node.get("id") or "")
        scene_nodes.append({
            **node,
            "renderX": round(float(node.get("renderX") or node.get("x") or 0), 2),
            "renderY": round(float(node.get("renderY") or node.get("y") or 0), 2),
            "node_scale": round(_timeline_node_render_scale(node_id, visibility, focus_active=focus_active), 3),
            "label_visible": visibility["node_ranks"].get(node_id, 1.0) <= label_rank_cutoff,
            "timeline_render_rank": round(visibility["node_ranks"].get(node_id, 1.0), 6),
            "timeline_focus": node_id in visibility["focus_node_ids"],
        })

    decade_rows: list[dict[str, float | int]] = []
    decade_buckets: dict[int, list[float]] = {}
    for node in nodes:
        year = node.get("year_start")
        y = node.get("y")
        if isinstance(year, int | float) and isinstance(y, int | float):
            decade_buckets.setdefault(math.floor(float(year) / 10) * 10, []).append(float(y))
    for decade, y_values in decade_buckets.items():
        decade_rows.append({"decade": decade, "y": round(sum(y_values) / max(1, len(y_values)), 2)})

    return {
        "nodes": scene_nodes,
        "edges": rendered_edges,
        "year_rows": sorted(decade_rows, key=lambda row: float(row["y"])),
        "render_signature": _timeline_render_signature(render_cutoff, viewport),
        "rank_signature": f"rank:{round(render_cutoff / _TIMELINE_RENDER_RANK_EPSILON)}",
        "focus_active": focus_active,
        "focus_node_ids": sorted(visibility["focus_node_ids"]),
        "scale": scale,
        "viewport": viewport,
    }


def _timeline_snapshots(
    data: dict[str, Any],
    *,
    selected_genre_id: str | None,
    chunk_size: int,
    scale: float = 1.0,
    viewport: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    nodes = sorted(
        list(data.get("nodes") or []),
        key=lambda node: _timeline_node_sort_key(node, selected_genre_id),
    )
    edges = list(data.get("edges") or [])
    stats = dict(data.get("stats") or {})
    bounds = _timeline_bounds(nodes)
    if bounds and "bounds" not in stats:
        stats["bounds"] = bounds

    snapshots: list[dict[str, Any]] = []
    visible_nodes: list[dict[str, Any]] = []
    visible_node_ids: set[str] = set()
    for start in range(0, len(nodes), chunk_size):
        batch = nodes[start : start + chunk_size]
        visible_nodes.extend(batch)
        visible_node_ids.update(str(node["id"]) for node in batch if node.get("id") is not None)
        visible_edges = [
            edge
            for edge in edges
            if edge.get("from_genre_id") in visible_node_ids and edge.get("to_genre_id") in visible_node_ids
        ]
        rank_max = max(
            (
                float(node.get("timeline_rank"))
                for node in visible_nodes
                if isinstance(node.get("timeline_rank"), int | float)
            ),
            default=0.0,
        )
        snapshot = {
            **data,
            "nodes": list(visible_nodes),
            "edges": visible_edges,
            "stats": {
                **stats,
                "stream_nodes": len(visible_nodes),
                "stream_edges": len(visible_edges),
            },
            "stream": {
                "rank_max": rank_max,
                "complete": len(visible_nodes) >= len(nodes),
            },
        }
        snapshot["render_scene"] = _prepare_timeline_scene(
            snapshot,
            selected_genre_id=selected_genre_id,
            scale=scale,
            viewport=viewport,
        )
        snapshots.append(snapshot)
    if snapshots:
        return snapshots
    empty = {**data, "stats": stats, "stream": {"rank_max": 0, "complete": True}}
    empty["render_scene"] = _prepare_timeline_scene(
        empty,
        selected_genre_id=selected_genre_id,
        scale=scale,
        viewport=viewport,
    )
    return [empty]


def _filter_timeline_viewport(
    data: dict[str, Any],
    *,
    x_min: float | None,
    x_max: float | None,
    y_min: float | None,
    y_max: float | None,
    selected_genre_id: str | None,
) -> dict[str, Any]:
    if x_min is None or x_max is None or y_min is None or y_max is None:
        return data

    nodes = list(data.get("nodes") or [])
    full_bounds = _timeline_bounds(nodes)
    visible_nodes = [
        node
        for node in nodes
        if (
            node.get("id") == selected_genre_id
            or (
                isinstance(node.get("x"), int | float)
                and isinstance(node.get("y"), int | float)
                and x_min <= float(node["x"]) <= x_max
                and y_min <= float(node["y"]) <= y_max
            )
        )
    ]
    visible_ids = {node.get("id") for node in visible_nodes}
    visible_edges = [
        edge
        for edge in list(data.get("edges") or [])
        if edge.get("from_genre_id") in visible_ids and edge.get("to_genre_id") in visible_ids
    ]
    stats = dict(data.get("stats") or {})
    if full_bounds:
        stats["bounds"] = full_bounds
    stats["viewport_nodes"] = len(visible_nodes)
    stats["viewport_edges"] = len(visible_edges)
    return {
        **data,
        "nodes": visible_nodes,
        "edges": visible_edges,
        "stats": stats,
    }


def _cloud_node_sort_key(
    node: dict[str, Any],
    selected_genre_id: str | None,
) -> tuple[int, int, float, float, float, float, float, str]:
    selected = selected_genre_id or "__music_root__"
    lod_rank = node.get("lod_rank")
    lod_tier = node.get("lod_tier")
    lod_score = node.get("lod_score")
    priority = node.get("priority")
    return (
        _cloud_anchor_rank(node, selected_genre_id),
        _cloud_selected_relationship_tier(node, selected_genre_id),
        0.0 if str(node.get("id")) == selected else 1.0,
        float(lod_rank) if isinstance(lod_rank, int | float) else 0.0,
        float(lod_tier) if isinstance(lod_tier, int | float) else 5.0,
        -float(lod_score) if isinstance(lod_score, int | float) else 0.0,
        -float(priority) if isinstance(priority, int | float) else 0.0,
        str(node.get("label") or node.get("wikipedia_title") or ""),
    )


def _cloud_scale_range(start: float, stop: float, step: float) -> tuple[float, ...]:
    values: list[float] = []
    value = start
    while value <= stop + 1e-9:
        values.append(round(value, 4))
        value += step
    return tuple(values)


_CLOUD_ATLAS_SCALES = tuple(dict.fromkeys((
    *_cloud_scale_range(0.12, 0.48, 0.02),
    *_cloud_scale_range(0.50, 0.90, 0.01),
    *_cloud_scale_range(0.905, 0.98, 0.005),
    *_cloud_scale_range(0.982, 0.998, 0.002),
    1.00,
)))
_CLOUD_ATLAS_TILE_PX = 360.0


def _cloud_box_width(node: dict[str, Any]) -> float:
    value = node.get("box_width")
    if value is not None:
        return float(value)
    return float(node.get("width") or 0.0)


def _cloud_box_height(node: dict[str, Any]) -> float:
    value = node.get("box_height")
    if value is not None:
        return float(value)
    return float(node.get("height") or 0.0)


def _cloud_scaled_rect(node: dict[str, Any], scale: float) -> tuple[float, float, float, float]:
    x = float(node.get("x") or 0.0) * scale
    y = float(node.get("y") or 0.0) * scale
    half_width = _cloud_box_width(node) / 2.0
    half_height = _cloud_box_height(node) / 2.0
    return (
        x - half_width,
        x + half_width,
        y - half_height,
        y + half_height,
    )


def _cloud_layer_tiles(
    nodes_by_id: dict[str, dict[str, Any]],
    node_ids: list[str],
    *,
    scale: float,
    tile_size: float = _CLOUD_ATLAS_TILE_PX,
) -> list[dict[str, Any]]:
    """Build render-ready layer tiles in layer-screen coordinates."""
    tiles: dict[tuple[int, int], list[str]] = {}
    for node_id in node_ids:
        node = nodes_by_id.get(str(node_id))
        if node is None:
            continue
        left, right, top, bottom = _cloud_scaled_rect(node, scale)
        min_x = math.floor(left / tile_size)
        max_x = math.floor(right / tile_size)
        min_y = math.floor(top / tile_size)
        max_y = math.floor(bottom / tile_size)
        for tile_x in range(min_x, max_x + 1):
            for tile_y in range(min_y, max_y + 1):
                tiles.setdefault((tile_x, tile_y), []).append(str(node_id))
    return [
        {"x": tile_x, "y": tile_y, "node_ids": ids}
        for (tile_x, tile_y), ids in sorted(tiles.items())
    ]


def _cloud_rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return a[0] < b[1] and a[1] > b[0] and a[2] < b[3] and a[3] > b[2]


class _CloudLayerSpatialIndex:
    def __init__(self, *, cell_size: float = 96.0) -> None:
        self.cell_size = cell_size
        self.cells: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}

    def _keys(self, rect: tuple[float, float, float, float]) -> tuple[range, range]:
        return (
            range(math.floor(rect[0] / self.cell_size), math.floor(rect[1] / self.cell_size) + 1),
            range(math.floor(rect[2] / self.cell_size), math.floor(rect[3] / self.cell_size) + 1),
        )

    def collides(self, rect: tuple[float, float, float, float]) -> bool:
        x_keys, y_keys = self._keys(rect)
        tested: set[int] = set()
        for key_x in x_keys:
            for key_y in y_keys:
                for existing in self.cells.get((key_x, key_y), ()):
                    marker = id(existing)
                    if marker in tested:
                        continue
                    tested.add(marker)
                    if _cloud_rects_overlap(rect, existing):
                        return True
        return False

    def add(self, rect: tuple[float, float, float, float]) -> None:
        x_keys, y_keys = self._keys(rect)
        for key_x in x_keys:
            for key_y in y_keys:
                self.cells.setdefault((key_x, key_y), []).append(rect)


def _cloud_scale_layers(
    nodes: list[dict[str, Any]],
    *,
    selected_genre_id: str | None,
) -> list[dict[str, Any]]:
    """Build monotonic, collision-valid raw-scale atlas layers."""
    nodes_by_id = {str(node["id"]): node for node in nodes if node.get("id") is not None}
    previous_ids: set[str] = set()
    layers: list[dict[str, Any]] = []
    for scale in _CLOUD_ATLAS_SCALES:
        if scale >= 1.0:
            layer_ids = [str(node["id"]) for node in nodes if node.get("id") is not None]
            previous_ids = set(layer_ids)
            layers.append({
                "scale": scale,
                "node_ids": layer_ids,
                "tile_size": _CLOUD_ATLAS_TILE_PX,
                "tiles": _cloud_layer_tiles(nodes_by_id, layer_ids, scale=scale),
            })
            continue

        occupied = _CloudLayerSpatialIndex()
        layer_ids: list[str] = []
        layer_id_set: set[str] = set()
        previous_nodes = [node for node in nodes if str(node.get("id")) in previous_ids]
        for node in previous_nodes:
            node_id = str(node.get("id"))
            rect = _cloud_scaled_rect(node, scale)
            # Lower-scale layers are subsets, so this should not collide. Keep the
            # guard to prevent malformed historical layouts from poisoning the layer.
            if occupied.collides(rect):
                continue
            occupied.add(rect)
            layer_ids.append(node_id)
            layer_id_set.add(node_id)

        for node in nodes:
            node_id = str(node.get("id"))
            if node_id in layer_id_set:
                continue
            rect = _cloud_scaled_rect(node, scale)
            if occupied.collides(rect):
                continue
            occupied.add(rect)
            layer_ids.append(node_id)
            layer_id_set.add(node_id)

        previous_ids = layer_id_set
        layers.append({
            "scale": scale,
            "node_ids": layer_ids,
            "tile_size": _CLOUD_ATLAS_TILE_PX,
            "tiles": _cloud_layer_tiles(nodes_by_id, layer_ids, scale=scale),
        })
    return layers


def _cloud_snapshots(
    data: dict[str, Any],
    *,
    selected_genre_id: str | None,
    chunk_size: int,
) -> list[dict[str, Any]]:
    return list(_iter_cloud_snapshots(data, selected_genre_id=selected_genre_id, chunk_size=chunk_size))


def _iter_cloud_snapshots(
    data: dict[str, Any],
    *,
    selected_genre_id: str | None,
    chunk_size: int,
) -> Iterable[dict[str, Any]]:
    nodes = sorted(
        list(data.get("nodes") or []),
        key=lambda node: _cloud_node_sort_key(node, selected_genre_id),
    )
    stats = dict(data.get("stats") or {})
    emitted = False
    for start in range(0, len(nodes), chunk_size):
        batch = nodes[start : start + chunk_size]
        emitted = True
        yield {
            **data,
            "nodes": batch,
            "stats": {
                **stats,
                "stream_nodes": min(start + len(batch), len(nodes)),
                "layer_nodes": len(batch),
            },
                "stream": {
                    "atlas": True,
                    "atlas_version": "cloud-render-atlas-v2",
                    "kind": "catalog",
                    "layer": "catalog",
                    "complete": False,
            },
        }

    scale_layers = _cloud_scale_layers(nodes, selected_genre_id=selected_genre_id)
    layer_stats = {
        **stats,
        "scale_layers": [
            {"scale": layer["scale"], "nodes": len(layer["node_ids"])}
            for layer in scale_layers
        ],
    }

    def scale_layer_snapshots(layer: dict[str, Any], previous_ids: set[str]) -> tuple[set[str], list[dict[str, Any]]]:
        node_ids = layer["node_ids"]
        layer_id_set = set(node_ids)
        add_node_ids = [node_id for node_id in node_ids if node_id not in previous_ids]
        remove_node_ids = sorted(previous_ids - layer_id_set)
        scale = float(layer["scale"])
        delta_ids = add_node_ids or []
        snapshots: list[dict[str, Any]] = []
        for start in range(0, max(1, len(delta_ids)), chunk_size):
            batch_ids = delta_ids[start : start + chunk_size]
            snapshots.append({
                **data,
                "nodes": [],
                "stats": {
                    **layer_stats,
                    "stream_nodes": len(nodes),
                    "layer_nodes": len(batch_ids),
                },
                "stream": {
                    "atlas": True,
                    "atlas_version": "cloud-render-atlas-v2",
                    "kind": "scale_layer",
                    "layer": f"scale:{scale:g}",
                    "scale": scale,
                    "tile_size": layer.get("tile_size", _CLOUD_ATLAS_TILE_PX),
                    "tiles": layer.get("tiles", []) if start == 0 else [],
                    "delta": True,
                    "base": not previous_ids,
                    "add_node_ids": batch_ids,
                    "remove_node_ids": remove_node_ids if start == 0 else [],
                    "visible_node_ids": batch_ids if not previous_ids else [],
                    "total_visible_nodes": len(node_ids),
                    "complete": False,
                },
            })
        return layer_id_set, snapshots

    previous_layer_ids: set[str] = set()
    for layer in scale_layers:
        previous_layer_ids, layer_snapshots = scale_layer_snapshots(layer, previous_layer_ids)
        for snapshot in layer_snapshots:
            emitted = True
            yield snapshot

    if not emitted:
        yield {
            **data,
            "nodes": [],
            "stats": layer_stats,
            "stream": {
                "atlas": True,
                "atlas_version": "cloud-render-atlas-v2",
                "layer": "empty",
                "lod_tier": 0,
                "complete": True,
            },
        }
        return

    yield {
        **data,
        "nodes": [],
        "stats": layer_stats,
        "stream": {
            "atlas": True,
            "atlas_version": "cloud-render-atlas-v2",
            "kind": "done",
            "layer": "complete",
            "complete": True,
        },
    }


async def _stream_snapshots(
    *,
    mode: Literal["cloud", "timeline"],
    snapshots: list[dict[str, Any]],
) -> AsyncIterator[str]:
    for index, snapshot in enumerate(snapshots):
        yield _line({
            "type": "snapshot",
            "mode": mode,
            "index": index,
            "complete": index == len(snapshots) - 1,
            "data": snapshot,
        })
    yield _line({"type": "complete", "mode": mode, "snapshots": len(snapshots)})


@router.get("/cloud/stream", response_class=StreamingResponse)
async def stream_cloud_render(
    limit: int = Query(5000, ge=25, le=5000),
    x_min: float | None = Query(None),
    x_max: float | None = Query(None),
    y_min: float | None = Query(None),
    y_max: float | None = Query(None),
    scale: float = Query(1.0, ge=0.05, le=6.0),
    view_tx: float = Query(0.0),
    view_ty: float = Query(0.0),
    root_genre_id: str | None = Query(None),
    region_id: str | None = Query(None),
    selected_genre_id: str | None = Query(None),
    chunk_size: int = Query(120, ge=25, le=500),
) -> StreamingResponse:
    """Stream progressively denser cloud snapshots for the current viewport."""
    async def generate() -> AsyncIterator[str]:
        yield _line({"type": "start", "mode": "cloud"})
        result = await get_genre_cloud(
            limit=limit,
            x_min=None,
            x_max=None,
            y_min=None,
            y_max=None,
            scale=scale,
            view_tx=view_tx,
            view_ty=view_ty,
            root_genre_id=root_genre_id,
            region_id=region_id,
            selected_genre_id=selected_genre_id,
            atlas=True,
        )
        data = jsonable_encoder(result)
        count = 0
        for snapshot in _iter_cloud_snapshots(data, selected_genre_id=selected_genre_id, chunk_size=chunk_size):
            yield _line({
                "type": "snapshot",
                "mode": "cloud",
                "index": count,
                "complete": bool(snapshot.get("stream", {}).get("complete")),
                "data": snapshot,
            })
            count += 1
        yield _line({"type": "complete", "mode": "cloud", "snapshots": count})

    return StreamingResponse(
        generate(),
        media_type=_STREAM_MEDIA_TYPE,
        headers=_STREAM_HEADERS,
    )


@router.get("/timeline/stream", response_class=StreamingResponse)
async def stream_timeline_render(
    genre_id: str | None = Query(None),
    scope: Literal["all", "descendants", "around"] = Query("all"),
    max_depth: int = Query(5, ge=1, le=8),
    max_nodes: int = Query(2400, ge=10, le=5000),
    max_rank: float = Query(1.0, ge=0.02, le=1.0),
    min_confidence: Literal["low", "medium", "high"] = Query("low"),
    selected_genre_id: str | None = Query(None),
    include_routes: bool = Query(False),
    chunk_size: int = Query(120, ge=25, le=500),
    x_min: float | None = Query(None),
    x_max: float | None = Query(None),
    y_min: float | None = Query(None),
    y_max: float | None = Query(None),
    scale: float = Query(1.0, ge=0.05, le=6.0),
    view_tx: float = Query(0.0),
    view_ty: float = Query(0.0),
    width: int | None = Query(None, ge=1),
    height: int | None = Query(None, ge=1),
) -> StreamingResponse:
    """Stream progressively denser timeline snapshots for the current viewport."""
    async def generate() -> AsyncIterator[str]:
        yield _line({"type": "start", "mode": "timeline"})
        result = await get_timeline(
            genre_id=genre_id,
            scope=scope,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_rank=max_rank,
            min_confidence=min_confidence,
            selected_genre_id=selected_genre_id,
            include_routes=include_routes,
        )
        viewport = (
            {"left": x_min, "right": x_max, "top": y_min, "bottom": y_max}
            if x_min is not None and x_max is not None and y_min is not None and y_max is not None
            else None
        )
        data = _filter_timeline_viewport(
            jsonable_encoder(result),
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            selected_genre_id=selected_genre_id,
        )
        data["stats"] = {
            **dict(data.get("stats") or {}),
            "scale": scale,
            "view_tx": view_tx,
            "view_ty": view_ty,
            "width": width or 0,
            "height": height or 0,
        }
        snapshots = _timeline_snapshots(
            data,
            selected_genre_id=selected_genre_id,
            chunk_size=chunk_size,
            scale=scale,
            viewport=viewport,
        )
        async for packet in _stream_snapshots(mode="timeline", snapshots=snapshots):
            yield packet

    return StreamingResponse(
        generate(),
        media_type=_STREAM_MEDIA_TYPE,
        headers=_STREAM_HEADERS,
    )
