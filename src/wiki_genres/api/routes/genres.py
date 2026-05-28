"""Routes: /v1/genres and /v1/genres/{id}/..."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import deque
from collections.abc import Iterable
from typing import Any, TypedDict

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from wiki_genres.api.models import (
    AliasOut,
    EdgeOut,
    GenreCloudNodeOut,
    GenreCloudResult,
    GenreDetail,
    GenreListItem,
    GenrePlaylistResult,
    GenrePlaylistTrackOut,
    MapContextOut,
    MapRegionItemOut,
    NeighborOut,
    OriginOut,
    PageviewEntry,
    PaginatedGenres,
    ReachableParentOut,
    RegionVariantOut,
    RegionVariantsResult,
)
from wiki_genres.cloud_text_metrics import (
    CLOUD_FONT_SIZE,
    CLOUD_LABEL_PAD_X,
    CLOUD_LABEL_PAD_Y,
    measure_cloud_label,
)
from wiki_genres.db import session_scope
from wiki_genres.loader.semantic_cloud_layout import layout_key_for_root

router = APIRouter(prefix="/v1/genres", tags=["genres"])

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
MAP_VARIANT_RELATIONS = ("regional_variations", *LEGACY_DISPLAY_RELATIONS)
MAP_VARIANT_EVIDENCE_RELATIONS = MAP_VARIANT_RELATIONS
RELATED_RELATION = "related_genre"
MUSIC_ROOT_ID = "__music_root__"
REGIONAL_SCENE_RELATION = "regional_scene"
REGIONAL_SCENE_EVIDENCE_RELATION = "regional_scene_of"
REGION_PARENT_RELATIONS = (
    *DISPLAY_RELATIONS,
    REGIONAL_SCENE_RELATION,
    "subclass_of",
)
MUSIC_REGION_TITLE_RE = re.compile(r"\bmusic\s+(?:of|in)\b", re.IGNORECASE)

WORLD_MAP_KEY = "world"
US_MAP_KEY = "us"
SPECIAL_REGION_MAPS = {
    "region-united-states": US_MAP_KEY,
}


WORLD_FEATURE_ALIASES = {
    "United States": "United States of America",
    "United States of America": "United States of America",
    "United Kingdom": "United Kingdom",
    "Czech Republic": "Czechia",
    "Côte d'Ivoire": "Côte d'Ivoire",
    "Ivory Coast": "Côte d'Ivoire",
    "Democratic Republic of the Congo": "Dem. Rep. Congo",
    "Republic of the Congo": "Congo",
    "Bosnia and Herzegovina": "Bosnia and Herz.",
    "North Macedonia": "Macedonia",
    "Dominican Republic": "Dominican Rep.",
    "Central African Republic": "Central African Rep.",
    "South Sudan": "S. Sudan",
    "Eswatini": "eSwatini",
}
US_FEATURE_ALIASES = {
    "District of Columbia": "District of Columbia",
    "Washington, D.C.": "District of Columbia",
    "U.S. Virgin Islands": "United States Virgin Islands",
    "Virgin Islands": "United States Virgin Islands",
    "Northern Mariana Islands": "Commonwealth of the Northern Mariana Islands",
}
ROOT_LIST_CONTINENT_NAMES = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
    "Americas",
)
US_FEATURE_NAMES = {
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "District of Columbia",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
    "American Samoa",
    "Guam",
    "Commonwealth of the Northern Mariana Islands",
    "Puerto Rico",
    "United States Virgin Islands",
}


def _display_title(title: str | None) -> str:
    label = (title or "").replace("_", " ").strip()
    label = re.sub(r"\s+\((music|genre|music genre)\)$", "", label, flags=re.I)
    label = re.sub(r"\s+music$", "", label, flags=re.I)
    return label or (title or "")


_CLOUD_FONT_SIZE = CLOUD_FONT_SIZE
_CLOUD_VIEWPORT_MARGIN_PX = 180.0
_CLOUD_ROOT_ID = "__music_root__"
_CLOUD_BOX_PAD_X = CLOUD_LABEL_PAD_X
_CLOUD_BOX_PAD_Y = CLOUD_LABEL_PAD_Y
_CLOUD_COLLISION_CELL_SIZE = 96.0


def _stable_unit(value: str) -> float:
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value / 4294967295


def _cloud_priority(row: dict) -> float:
    value = row.get("priority")
    if value is not None:
        return float(value)
    return math.log(max(0, row.get("monthly_views_p30") or 0) + 1)


def _cloud_label_word_count(label: str | None) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", label or ""))


def _cloud_overlong_label_penalty(label: str | None) -> int:
    return max(0, _cloud_label_word_count(label) - 3)


def _cloud_regional_phrase_penalty(label: str | None) -> int:
    text = (label or "").strip().lower()
    return 1 if re.search(r"\bmusic\s+(?:of|in)\b", text) else 0


def _cloud_label_metrics(label: str | None) -> dict[str, float]:
    metrics = measure_cloud_label(label)
    return {
        "width": metrics.text_width,
        "height": metrics.text_height,
        "text_width": metrics.text_width,
        "text_height": metrics.text_height,
        "box_width": metrics.box_width,
        "box_height": metrics.box_height,
        "box_pad_x": metrics.box_pad_x,
        "box_pad_y": metrics.box_pad_y,
    }


def _layout_cloud_nodes(
    rows: list[dict], *, center_id: str = _CLOUD_ROOT_ID, center_title: str = "Music"
) -> list[dict]:
    center_row = next((row for row in rows if row.get("id") == center_id), None)
    center_label = (
        _display_title(center_row.get("wikipedia_title"))
        if center_row
        else _display_title(center_title)
    )
    center_node = {
        **(center_row or {}),
        "id": center_id,
        "wikipedia_title": center_row.get("wikipedia_title") if center_row else center_title,
        "label": center_label,
        "depth_from_music": 0,
        "semantic_root_id": center_id,
        "semantic_root_title": center_row.get("wikipedia_title") if center_row else center_title,
        "monthly_views_p30": center_row.get("monthly_views_p30") if center_row else None,
        "similarity_color": center_row.get("similarity_color") if center_row else None,
        "color_confidence": center_row.get("color_confidence") if center_row else 1.0,
        "has_playlist": bool(center_row.get("has_playlist")) if center_row else False,
        "child_connection_count": center_row.get("child_connection_count") if center_row else 0,
        "parent_connection_count": center_row.get("parent_connection_count") if center_row else 0,
        "priority": 1_000_000.0,
        "lod_score": 1.0,
        "min_visible_scale": 0.0,
        "show_scale": 0.0,
        "hide_scale": 0.0,
        "lod_rank": -1,
        "lod_tier": 0,
        "x": 0.0,
        "y": 0.0,
        **_cloud_label_metrics(center_label),
    }
    rows = [row for row in rows if row.get("id") != center_id]
    if not rows:
        return [center_node]

    root_weights: dict[str, float] = {}
    for row in rows:
        root = row.get("semantic_root_title") or "Other"
        root_weights[root] = root_weights.get(root, 0.0) + _cloud_priority(row)
    root_names = [
        item[0]
        for item in sorted(root_weights.items(), key=lambda item: (-item[1], item[0].lower()))
    ]
    root_angles = {
        root: (-math.pi / 2) + (index / max(1, len(root_names))) * math.pi * 2
        for index, root in enumerate(root_names)
    }
    priorities = [_cloud_priority(row) for row in rows]
    max_priority = max(1.0, *priorities)
    min_priority = min(*priorities, max_priority)
    span = max(1.0, max_priority - min_priority)

    nodes = [center_node]
    for index, row in enumerate(rows):
        label = _display_title(row.get("wikipedia_title"))
        root = row.get("semantic_root_title") or "Other"
        priority = (
            _cloud_priority(row)
            - (_cloud_regional_phrase_penalty(label) * 1_000_000_000_000)
            - (_cloud_overlong_label_penalty(label) * 1_000_000)
        )
        priority_norm = max(0.0, min(1.0, (priority - min_priority) / span))
        depth = max(1, int(row.get("depth_from_music") or 5))
        angle = (
            root_angles.get(root, 0.0)
            + (_stable_unit(f"{row['id']}:angle") - 0.5) * 0.9
            + (index % 7) * 0.012
        )
        radius = (
            180
            + depth * 175
            + (1 - priority_norm) * 460
            + (_stable_unit(f"{row['id']}:radius") - 0.5) * 170
        )
        nodes.append(
            {
                **row,
                "label": label,
                "priority": priority,
                "x": math.cos(angle) * radius * 1.18,
                "y": math.sin(angle) * radius * 0.86,
                **_cloud_label_metrics(label),
            }
        )
    return nodes


def _apply_materialized_cloud_layout(
    nodes: list[dict],
    layout_rows: list[dict],
) -> tuple[list[dict], int, int]:
    layout_by_id = {row["genre_id"]: row for row in layout_rows}
    applied = 0
    radial_applied = 0
    materialized_nodes: list[dict] = []
    for node in nodes:
        layout = layout_by_id.get(node["id"])
        if not layout:
            materialized_nodes.append(node)
            continue
        min_visible_scale = layout.get("min_visible_scale")
        show_scale = layout.get("show_scale")
        hide_scale = layout.get("hide_scale")
        lod_score = layout.get("lod_score")
        lod_rank = layout.get("lod_rank")
        lod_tier = layout.get("lod_tier")
        radial_x = layout.get("radial_x")
        radial_y = layout.get("radial_y")
        fallback_metrics = _cloud_label_metrics(node.get("label") or node.get("wikipedia_title"))
        text_width = float(layout.get("text_width") or 0.0) or fallback_metrics["text_width"]
        text_height = float(layout.get("text_height") or 0.0) or fallback_metrics["text_height"]
        box_pad_x = float(layout.get("box_pad_x") or _CLOUD_BOX_PAD_X)
        box_pad_y = float(layout.get("box_pad_y") or _CLOUD_BOX_PAD_Y)
        box_width = float(layout.get("box_width") or 0.0) or text_width + box_pad_x * 2
        box_height = float(layout.get("box_height") or 0.0) or text_height + box_pad_y * 2
        display_x = radial_x if radial_x is not None and radial_y is not None else layout["x"]
        display_y = radial_y if radial_x is not None and radial_y is not None else layout["y"]
        if radial_x is not None and radial_y is not None:
            radial_applied += 1
        applied += 1
        materialized_nodes.append(
            {
                **node,
                "x": float(display_x),
                "y": float(display_y),
                "width": text_width,
                "height": text_height,
                "text_width": text_width,
                "text_height": text_height,
                "box_width": box_width,
                "box_height": box_height,
                "box_pad_x": box_pad_x,
                "box_pad_y": box_pad_y,
                "priority": float(layout["priority"]),
                "lod_score": float(lod_score) if lod_score is not None else 0.0,
                "radial_x": float(radial_x) if radial_x is not None else None,
                "radial_y": float(radial_y) if radial_y is not None else None,
                "radial_compaction_version": layout.get("radial_compaction_version"),
                "min_visible_scale": (
                    float(min_visible_scale) if min_visible_scale is not None else 2.0
                ),
                "show_scale": (
                    float(show_scale)
                    if show_scale is not None
                    else float(min_visible_scale)
                    if min_visible_scale is not None
                    else 2.0
                ),
                "hide_scale": float(hide_scale) if hide_scale is not None else 1.85,
                "lod_rank": int(lod_rank) if lod_rank is not None else 0,
                "lod_tier": int(lod_tier) if lod_tier is not None else 5,
            }
        )
    return materialized_nodes, applied, radial_applied


def _apply_cloud_display_cache(
    nodes: list[dict],
    display_rows: list[dict],
) -> tuple[list[dict], int, int]:
    display_by_id = {row["genre_id"]: row for row in display_rows}
    applied = 0
    radial_applied = 0
    cached_nodes: list[dict] = []
    for node in nodes:
        layout = display_by_id.get(node["id"])
        if not layout:
            cached_nodes.append(node)
            continue
        applied += 1
        if int(layout.get("display_source") or 0) == 2:
            radial_applied += 1
        cached_nodes.append(
            {
                **node,
                "x": float(layout["x"]),
                "y": float(layout["y"]),
                "width": float(layout["text_width"]),
                "height": float(layout["text_height"]),
                "text_width": float(layout["text_width"]),
                "text_height": float(layout["text_height"]),
                "box_width": float(layout["box_width"]),
                "box_height": float(layout["box_height"]),
                "box_pad_x": float(layout["box_pad_x"]),
                "box_pad_y": float(layout["box_pad_y"]),
                "priority": float(layout["priority"]),
                "lod_score": float(layout["lod_score"]),
                "min_visible_scale": float(layout["min_visible_scale"]),
                "show_scale": float(layout["show_scale"]),
                "hide_scale": float(layout["hide_scale"]),
                "lod_rank": int(layout["lod_rank"]),
                "lod_tier": int(layout["lod_tier"]),
            }
        )
    return cached_nodes, applied, radial_applied


def _cloud_bounds(nodes: list[dict]) -> dict[str, float]:
    return {
        "min_x": min(node["x"] - _cloud_box_width(node) / 2 for node in nodes),
        "max_x": max(node["x"] + _cloud_box_width(node) / 2 for node in nodes),
        "min_y": min(node["y"] - _cloud_box_height(node) / 2 for node in nodes),
        "max_y": max(node["y"] + _cloud_box_height(node) / 2 for node in nodes),
    }


def _cloud_box_width(node: dict) -> float:
    value = node.get("box_width")
    if value is not None:
        return float(value)
    return float(node["width"]) + _CLOUD_BOX_PAD_X * 2


def _cloud_box_height(node: dict) -> float:
    value = node.get("box_height")
    if value is not None:
        return float(value)
    return float(node["height"]) + _CLOUD_BOX_PAD_Y * 2


def _cloud_viewport_candidates(
    nodes: list[dict],
    *,
    x_min: float | None,
    x_max: float | None,
    y_min: float | None,
    y_max: float | None,
    scale: float,
    selected_genre_id: str | None,
) -> list[dict]:
    margin_world = _CLOUD_VIEWPORT_MARGIN_PX / max(0.001, scale)
    if x_min is not None and x_max is not None and y_min is not None and y_max is not None:
        candidates = [
            node
            for node in nodes
            if (
                node["x"] + _cloud_box_width(node) / 2 >= x_min - margin_world
                and node["x"] - _cloud_box_width(node) / 2 <= x_max + margin_world
                and node["y"] + _cloud_box_height(node) / 2 >= y_min - margin_world
                and node["y"] - _cloud_box_height(node) / 2 <= y_max + margin_world
            )
        ]
    else:
        candidates = list(nodes)

    selected = selected_genre_id or _CLOUD_ROOT_ID
    if selected and not any(node["id"] == selected for node in candidates):
        selected_node = next((node for node in nodes if node["id"] == selected), None)
        if selected_node:
            candidates.append(selected_node)
    return candidates


def _sort_cloud_nodes(candidates: list[dict], *, selected_genre_id: str | None) -> list[dict]:
    selected = selected_genre_id or _CLOUD_ROOT_ID
    return sorted(
        candidates,
        key=lambda node: (
            _cloud_anchor_rank(node, selected_genre_id),
            _cloud_selected_relationship_tier(node, selected_genre_id),
            node["id"] != selected,
            int(node.get("lod_rank") or 0),
            int(node.get("lod_tier") or 0),
            -float(node.get("lod_score") or 0.0),
            -float(node.get("priority") or 0.0),
            node["label"].lower(),
        ),
    )


def _cloud_anchor_rank(node: dict, selected_genre_id: str | None) -> int:
    node_id = str(node.get("id") or "")
    if selected_genre_id and selected_genre_id != _CLOUD_ROOT_ID and node_id == selected_genre_id:
        return 0
    if node_id == _CLOUD_ROOT_ID:
        return 1
    return 2


def _cloud_selected_relationship_tier(node: dict, selected_genre_id: str | None) -> int:
    if not selected_genre_id or selected_genre_id == _CLOUD_ROOT_ID:
        return 0
    if str(node.get("id") or "") == selected_genre_id:
        return 0
    distance = node.get("selected_distance")
    if isinstance(distance, bool) or not isinstance(distance, int | float):
        return 99
    if not math.isfinite(float(distance)):
        return 99
    return max(0, min(98, int(distance)))


def _cloud_screen_rect(
    node: dict, scale: float, view_tx: float, view_ty: float
) -> dict[str, float]:
    x = node["x"] * scale + view_tx
    y = node["y"] * scale + view_ty
    width = _cloud_box_width(node)
    height = _cloud_box_height(node)
    return {
        "left": x - width / 2,
        "right": x + width / 2,
        "top": y - height / 2,
        "bottom": y + height / 2,
    }


def _rects_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["left"] < b["right"]
        and a["right"] > b["left"]
        and a["top"] < b["bottom"]
        and a["bottom"] > b["top"]
    )


class _CloudScreenSpatialIndex:
    def __init__(self, *, cell_size: float = _CLOUD_COLLISION_CELL_SIZE) -> None:
        self.cell_size = cell_size
        self.cells: dict[tuple[int, int], list[dict[str, float]]] = {}

    def _keys(self, rect: dict[str, float]) -> tuple[range, range]:
        x_keys = range(
            math.floor(rect["left"] / self.cell_size),
            math.floor(rect["right"] / self.cell_size) + 1,
        )
        y_keys = range(
            math.floor(rect["top"] / self.cell_size),
            math.floor(rect["bottom"] / self.cell_size) + 1,
        )
        return x_keys, y_keys

    def collides(self, rect: dict[str, float]) -> bool:
        x_keys, y_keys = self._keys(rect)
        tested: set[int] = set()
        for key_x in x_keys:
            for key_y in y_keys:
                for existing in self.cells.get((key_x, key_y), ()):
                    marker = id(existing)
                    if marker in tested:
                        continue
                    tested.add(marker)
                    if _rects_overlap(rect, existing):
                        return True
        return False

    def add(self, rect: dict[str, float]) -> None:
        x_keys, y_keys = self._keys(rect)
        for key_x in x_keys:
            for key_y in y_keys:
                self.cells.setdefault((key_x, key_y), []).append(rect)


def _cull_cloud_nodes(
    nodes: list[dict],
    *,
    x_min: float | None,
    x_max: float | None,
    y_min: float | None,
    y_max: float | None,
    scale: float,
    view_tx: float,
    view_ty: float,
    selected_genre_id: str | None,
    limit: int | None,
) -> list[dict]:
    candidates = _cloud_viewport_candidates(
        nodes,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        scale=scale,
        selected_genre_id=selected_genre_id,
    )
    selected = selected_genre_id or _CLOUD_ROOT_ID
    visible: list[dict] = []
    occupied = _CloudScreenSpatialIndex()
    for node in _sort_cloud_nodes(candidates, selected_genre_id=selected):
        rect = _cloud_screen_rect(node, scale, view_tx, view_ty)
        force_visible = node["id"] == selected
        if not force_visible and occupied.collides(rect):
            continue
        visible.append(node)
        occupied.add(rect)
        if limit is not None and len(visible) >= limit:
            break
    return visible


def _viewport_cloud_nodes(
    nodes: list[dict],
    *,
    x_min: float | None,
    x_max: float | None,
    y_min: float | None,
    y_max: float | None,
    scale: float,
    selected_genre_id: str | None,
    limit: int,
) -> list[dict]:
    candidates = _cloud_viewport_candidates(
        nodes,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        scale=scale,
        selected_genre_id=selected_genre_id,
    )
    return _sort_cloud_nodes(candidates, selected_genre_id=selected_genre_id)[:limit]


def _cloud_selected_distance_opacity_score(distance: int, strongest_edge: float) -> float:
    distance_score = max(0.0, 1.0 - distance * 0.22)
    edge_score = max(0.0, min(1.0, strongest_edge))
    return round(max(0.0, min(1.0, distance_score * 0.74 + edge_score * 0.26)), 4)


def _cloud_selected_distance_map(
    edges: Iterable[dict],
    *,
    selected_genre_id: str | None,
    max_depth: int = 4,
) -> dict[str, dict[str, int | float]]:
    if not selected_genre_id or selected_genre_id == _CLOUD_ROOT_ID:
        return {}

    adjacency: dict[str, list[tuple[str, float]]] = {}
    for edge in edges:
        left_id = edge.get("from_genre_id")
        right_id = edge.get("to_genre_id")
        if not left_id or not right_id or left_id == right_id:
            continue
        weight = max(0.0, min(1.0, float(edge.get("weight") or 0.0)))
        adjacency.setdefault(left_id, []).append((right_id, weight))
        adjacency.setdefault(right_id, []).append((left_id, weight))

    distances: dict[str, dict[str, int | float]] = {
        selected_genre_id: {"distance": 0, "score": 1.0}
    }
    queue: deque[tuple[str, int, float]] = deque([(selected_genre_id, 0, 1.0)])
    while queue:
        genre_id, distance, path_strength = queue.popleft()
        if distance >= max_depth:
            continue
        for neighbor_id, edge_weight in adjacency.get(genre_id, ()):
            next_distance = distance + 1
            next_strength = path_strength * max(0.18, edge_weight)
            current = distances.get(neighbor_id)
            if current is not None:
                if next_distance < int(current["distance"]):
                    current["distance"] = next_distance
                    current["score"] = _cloud_selected_distance_opacity_score(
                        next_distance,
                        next_strength,
                    )
                    queue.append((neighbor_id, next_distance, next_strength))
                continue
            distances[neighbor_id] = {
                "distance": next_distance,
                "score": _cloud_selected_distance_opacity_score(next_distance, next_strength),
            }
            queue.append((neighbor_id, next_distance, next_strength))
    return distances


def _apply_cloud_selected_distances(
    nodes: list[dict],
    distances: dict[str, dict[str, int | float]],
) -> list[dict]:
    if not distances:
        return nodes
    applied: list[dict] = []
    for node in nodes:
        distance = distances.get(node.get("id"))
        if not distance:
            applied.append(node)
            continue
        applied.append(
            {
                **node,
                "selected_distance": int(distance["distance"]),
                "selected_focus_score": float(distance["score"]),
            }
        )
    return applied


class Region(TypedDict):
    key: str
    name: str
    of: str
    demonyms: list[str]
    x: float
    y: float


REGIONS: list[Region] = [
    {
        "key": "us",
        "name": "United States",
        "of": "the United States",
        "demonyms": ["American"],
        "x": 72,
        "y": 74,
    },
    {"key": "ca", "name": "Canada", "of": "Canada", "demonyms": ["Canadian"], "x": 70, "y": 51},
    {"key": "mx", "name": "Mexico", "of": "Mexico", "demonyms": ["Mexican"], "x": 83, "y": 96},
    {"key": "br", "name": "Brazil", "of": "Brazil", "demonyms": ["Brazilian"], "x": 139, "y": 130},
    {
        "key": "ar",
        "name": "Argentina",
        "of": "Argentina",
        "demonyms": ["Argentine", "Argentinian"],
        "x": 129,
        "y": 154,
    },
    {
        "key": "co",
        "name": "Colombia",
        "of": "Colombia",
        "demonyms": ["Colombian"],
        "x": 115,
        "y": 115,
    },
    {"key": "cu", "name": "Cuba", "of": "Cuba", "demonyms": ["Cuban"], "x": 104, "y": 93},
    {"key": "jm", "name": "Jamaica", "of": "Jamaica", "demonyms": ["Jamaican"], "x": 110, "y": 96},
    {
        "key": "ve",
        "name": "Venezuela",
        "of": "Venezuela",
        "demonyms": ["Venezuelan"],
        "x": 123,
        "y": 111,
    },
    {
        "key": "uk",
        "name": "United Kingdom",
        "of": "the United Kingdom",
        "demonyms": ["British"],
        "x": 153,
        "y": 59,
    },
    {"key": "ie", "name": "Ireland", "of": "Ireland", "demonyms": ["Irish"], "x": 146, "y": 60},
    {"key": "fr", "name": "France", "of": "France", "demonyms": ["French"], "x": 158, "y": 70},
    {"key": "de", "name": "Germany", "of": "Germany", "demonyms": ["German"], "x": 169, "y": 66},
    {"key": "it", "name": "Italy", "of": "Italy", "demonyms": ["Italian"], "x": 173, "y": 78},
    {"key": "es", "name": "Spain", "of": "Spain", "demonyms": ["Spanish"], "x": 153, "y": 81},
    {
        "key": "pt",
        "name": "Portugal",
        "of": "Portugal",
        "demonyms": ["Portuguese"],
        "x": 148,
        "y": 82,
    },
    {
        "key": "nl",
        "name": "Netherlands",
        "of": "the Netherlands",
        "demonyms": ["Dutch"],
        "x": 164,
        "y": 63,
    },
    {"key": "be", "name": "Belgium", "of": "Belgium", "demonyms": ["Belgian"], "x": 162, "y": 66},
    {"key": "se", "name": "Sweden", "of": "Sweden", "demonyms": ["Swedish"], "x": 174, "y": 48},
    {"key": "no", "name": "Norway", "of": "Norway", "demonyms": ["Norwegian"], "x": 169, "y": 45},
    {"key": "fi", "name": "Finland", "of": "Finland", "demonyms": ["Finnish"], "x": 184, "y": 45},
    {"key": "dk", "name": "Denmark", "of": "Denmark", "demonyms": ["Danish"], "x": 168, "y": 57},
    {"key": "pl", "name": "Poland", "of": "Poland", "demonyms": ["Polish"], "x": 180, "y": 66},
    {"key": "gr", "name": "Greece", "of": "Greece", "demonyms": ["Greek"], "x": 184, "y": 85},
    {"key": "tr", "name": "Turkey", "of": "Turkey", "demonyms": ["Turkish"], "x": 200, "y": 84},
    {"key": "ru", "name": "Russia", "of": "Russia", "demonyms": ["Russian"], "x": 218, "y": 54},
    {"key": "eg", "name": "Egypt", "of": "Egypt", "demonyms": ["Egyptian"], "x": 194, "y": 101},
    {"key": "ma", "name": "Morocco", "of": "Morocco", "demonyms": ["Moroccan"], "x": 154, "y": 96},
    {"key": "dz", "name": "Algeria", "of": "Algeria", "demonyms": ["Algerian"], "x": 166, "y": 99},
    {"key": "ng", "name": "Nigeria", "of": "Nigeria", "demonyms": ["Nigerian"], "x": 178, "y": 119},
    {"key": "gh", "name": "Ghana", "of": "Ghana", "demonyms": ["Ghanaian"], "x": 170, "y": 121},
    {
        "key": "za",
        "name": "South Africa",
        "of": "South Africa",
        "demonyms": ["South African"],
        "x": 188,
        "y": 157,
    },
    {
        "key": "et",
        "name": "Ethiopia",
        "of": "Ethiopia",
        "demonyms": ["Ethiopian"],
        "x": 205,
        "y": 117,
    },
    {"key": "ke", "name": "Kenya", "of": "Kenya", "demonyms": ["Kenyan"], "x": 207, "y": 128},
    {"key": "in", "name": "India", "of": "India", "demonyms": ["Indian"], "x": 235, "y": 105},
    {
        "key": "pk",
        "name": "Pakistan",
        "of": "Pakistan",
        "demonyms": ["Pakistani"],
        "x": 227,
        "y": 98,
    },
    {
        "key": "bd",
        "name": "Bangladesh",
        "of": "Bangladesh",
        "demonyms": ["Bangladeshi"],
        "x": 249,
        "y": 103,
    },
    {
        "key": "lk",
        "name": "Sri Lanka",
        "of": "Sri Lanka",
        "demonyms": ["Sri Lankan"],
        "x": 240,
        "y": 123,
    },
    {"key": "cn", "name": "China", "of": "China", "demonyms": ["Chinese"], "x": 264, "y": 88},
    {"key": "tw", "name": "Taiwan", "of": "Taiwan", "demonyms": ["Taiwanese"], "x": 286, "y": 101},
    {"key": "jp", "name": "Japan", "of": "Japan", "demonyms": ["Japanese"], "x": 298, "y": 82},
    {
        "key": "kr",
        "name": "South Korea",
        "of": "South Korea",
        "demonyms": ["Korean"],
        "x": 286,
        "y": 83,
    },
    {
        "key": "kp",
        "name": "North Korea",
        "of": "North Korea",
        "demonyms": ["Korean"],
        "x": 284,
        "y": 78,
    },
    {
        "key": "ph",
        "name": "Philippines",
        "of": "the Philippines",
        "demonyms": ["Philippine", "Filipino"],
        "x": 286,
        "y": 117,
    },
    {
        "key": "id",
        "name": "Indonesia",
        "of": "Indonesia",
        "demonyms": ["Indonesian"],
        "x": 273,
        "y": 135,
    },
    {
        "key": "my",
        "name": "Malaysia",
        "of": "Malaysia",
        "demonyms": ["Malaysian"],
        "x": 268,
        "y": 124,
    },
    {"key": "th", "name": "Thailand", "of": "Thailand", "demonyms": ["Thai"], "x": 261, "y": 115},
    {
        "key": "vn",
        "name": "Vietnam",
        "of": "Vietnam",
        "demonyms": ["Vietnamese"],
        "x": 270,
        "y": 112,
    },
    {
        "key": "au",
        "name": "Australia",
        "of": "Australia",
        "demonyms": ["Australian"],
        "x": 285,
        "y": 154,
    },
    {
        "key": "nz",
        "name": "New Zealand",
        "of": "New Zealand",
        "demonyms": ["New Zealand"],
        "x": 312,
        "y": 162,
    },
]


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


async def _get_genre_row(session, genre_id: str, include_deleted: bool = False):
    """Fetch the core wg_genres row by ID."""
    deleted_filter = "" if include_deleted else "AND g.deleted_at IS NULL"
    query = """
        SELECT g.*,
               c.color_hex AS similarity_color,
               c.confidence AS color_confidence,
               layout.text_width,
               layout.text_height,
               layout.box_width,
               layout.box_height,
               layout.box_pad_x,
               layout.box_pad_y
        FROM wg_genres g
        LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
        LEFT JOIN wg_genre_semantic_layouts layout
          ON layout.genre_id = g.id
         AND layout.layout_key = :layout_key
        WHERE g.id = :id
          AND g.is_non_genre = false
    """
    if deleted_filter:
        query += "\n          AND g.deleted_at IS NULL"
    row = await session.execute(
        text(query),
        {"id": genre_id, "layout_key": layout_key_for_root(None)},
    )
    return row.mappings().fetchone()


async def _build_genre_detail(session, row) -> GenreDetail:
    """Assemble a GenreDetail from a wg_genres row plus related tables."""
    gid = row["id"]
    layout_key = layout_key_for_root(None)

    edges_out = (
        (
            await session.execute(
                text("""
            SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                   e.relation, e.source, e.ordinal, e.evidence_relation,
                   to_g.monthly_views_p30 AS to_monthly_views_p30,
                   to_c.color_hex AS to_similarity_color,
                   to_c.confidence AS to_color_confidence,
                   to_layout.text_width AS to_text_width,
                   to_layout.text_height AS to_text_height,
                   to_layout.box_width AS to_box_width,
                   to_layout.box_height AS to_box_height,
                   to_layout.box_pad_x AS to_box_pad_x,
                   to_layout.box_pad_y AS to_box_pad_y
            FROM wg_relationship_detail_edges e
            LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
            LEFT JOIN wg_genre_colors to_c ON to_c.genre_id = e.to_genre_id
            LEFT JOIN wg_genre_semantic_layouts to_layout
              ON to_layout.genre_id = e.to_genre_id
             AND to_layout.layout_key = :layout_key
            WHERE e.from_genre_id = :gid
              AND e.is_ignored = false
              AND (
                e.to_genre_id IS NULL
                OR (to_g.deleted_at IS NULL AND to_g.is_non_genre = false)
              )
            ORDER BY e.relation, e.source, e.ordinal
        """),
                {"gid": gid, "layout_key": layout_key},
            )
        )
        .mappings()
        .fetchall()
    )

    edges_in = (
        (
            await session.execute(
                text("""
            SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                   e.relation, e.source, e.ordinal, e.evidence_relation,
                   to_g.monthly_views_p30 AS to_monthly_views_p30,
                   to_c.color_hex AS to_similarity_color,
                   to_c.confidence AS to_color_confidence,
                   to_layout.text_width AS to_text_width,
                   to_layout.text_height AS to_text_height,
                   to_layout.box_width AS to_box_width,
                   to_layout.box_height AS to_box_height,
                   to_layout.box_pad_x AS to_box_pad_x,
                   to_layout.box_pad_y AS to_box_pad_y
            FROM wg_relationship_detail_edges e
            JOIN wg_genres g ON g.id = e.from_genre_id
            LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
            LEFT JOIN wg_genre_colors to_c ON to_c.genre_id = e.to_genre_id
            LEFT JOIN wg_genre_semantic_layouts to_layout
              ON to_layout.genre_id = e.to_genre_id
             AND to_layout.layout_key = :layout_key
            WHERE e.to_genre_id = :gid
              AND e.is_ignored = false
              AND g.deleted_at IS NULL
              AND g.is_non_genre = false
            ORDER BY e.relation, e.source, e.ordinal
        """),
                {"gid": gid, "layout_key": layout_key},
            )
        )
        .mappings()
        .fetchall()
    )

    aliases = (
        (
            await session.execute(
                text("SELECT alias, source FROM wg_aliases WHERE genre_id = :gid ORDER BY alias"),
                {"gid": gid},
            )
        )
        .mappings()
        .fetchall()
    )

    origins = (
        (
            await session.execute(
                text("""
            SELECT kind, value, parsed_year_start, parsed_year_end, parsed_region
            FROM wg_origins WHERE genre_id = :gid
        """),
                {"gid": gid},
            )
        )
        .mappings()
        .fetchall()
    )

    instruments = (
        (
            await session.execute(
                text("""
                    SELECT instrument
                    FROM wg_instruments
                    WHERE genre_id = :gid
                    ORDER BY instrument
                """),
                {"gid": gid},
            )
        )
        .mappings()
        .fetchall()
    )

    categories = (
        (
            await session.execute(
                text("SELECT category FROM wg_categories WHERE genre_id = :gid ORDER BY category"),
                {"gid": gid},
            )
        )
        .mappings()
        .fetchall()
    )

    youtube_items = (
        (
            await session.execute(
                text(f"""
                    SELECT tracks.genre_id, tracks.ordinal, tracks.song_title, tracks.artist, tracks.youtube_url
                    FROM wg_genre_approved_client_playlist_tracks tracks
                    WHERE tracks.genre_id = :gid
                    ORDER BY
                        tracks.ordinal,
                        tracks.artist,
                        tracks.song_title
                """),
                {"gid": gid},
            )
        )
        .mappings()
        .fetchall()
    )

    return GenreDetail(
        id=row["id"],
        wikidata_qid=row["wikidata_qid"],
        wikipedia_title=row["wikipedia_title"],
        wikipedia_url=row["wikipedia_url"],
        has_infobox=row["has_infobox"],
        infobox_color=row["infobox_color"],
        similarity_color=row["similarity_color"],
        color_confidence=row["color_confidence"],
        text_width=row["text_width"],
        text_height=row["text_height"],
        box_width=row["box_width"],
        box_height=row["box_height"],
        box_pad_x=row["box_pad_x"],
        box_pad_y=row["box_pad_y"],
        summary=row["summary"],
        last_changed_at=row["last_changed_at"],
        last_fetched_at=row["last_fetched_at"],
        outbound_edges=[EdgeOut(**dict(e)) for e in edges_out],
        inbound_edges=[EdgeOut(**dict(e)) for e in edges_in],
        aliases=[AliasOut(**dict(a)) for a in aliases],
        origins=[OriginOut(**dict(o)) for o in origins],
        instruments=[r["instrument"] for r in instruments],
        categories=[r["category"] for r in categories],
        youtube_items=[GenrePlaylistTrackOut(**dict(item)) for item in youtube_items],
        youtube_urls=[item["youtube_url"] for item in youtube_items],
    )


def _label_for_region_match(title: str) -> str:
    label = title.replace("_", " ").strip()
    for suffix in (" (music)", " (genre)", " (music genre)"):
        if label.lower().endswith(suffix):
            label = label[: -len(suffix)]
            break
    if label.lower().endswith(" music"):
        label = label[:-6]
    return " ".join(label.split())


def _regional_title_candidates(title: str, region: Region) -> set[str]:
    base = _label_for_region_match(title)
    base_lower = base.lower()
    of_name = str(region["of"]).lower()
    country_name = str(region["name"]).lower()
    candidates = {
        f"{base_lower} in {country_name}",
        f"{base_lower} in {of_name}",
        f"{base_lower} music in {country_name}",
        f"{base_lower} music in {of_name}",
        f"{base_lower} of {country_name}",
        f"{base_lower} of {of_name}",
        f"{base_lower} music of {country_name}",
        f"{base_lower} music of {of_name}",
    }
    for demonym in region["demonyms"]:
        demonym_lower = str(demonym).lower()
        candidates.add(f"{demonym_lower} {base_lower}")
        candidates.add(f"{demonym_lower} {base_lower} music")
    return {candidate for candidate in candidates if candidate.strip()}


def _music_region_title(region: Region) -> str:
    return f"music of {str(region['of']).lower()}"


def _slug_region_key(name: str, *, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return f"region-{slug or fallback}"


def _feature_key_for_region(region_name: str, *, map_key: str) -> str:
    if map_key == US_MAP_KEY:
        return US_FEATURE_ALIASES.get(region_name, region_name)
    return WORLD_FEATURE_ALIASES.get(region_name, region_name)


def _region_map_key(region_id: str | None, *, default: str = WORLD_MAP_KEY) -> str:
    if not region_id:
        return default
    return SPECIAL_REGION_MAPS.get(region_id, default)


def _selectable_for_label(country_name: str, item: MapRegionItemOut) -> str:
    return item.display_title or item.wikipedia_title or item.region_name or country_name


def _represented_genre_ids(*values: str | None) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _represented_titles(*values: str | None) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _normalized_region_match_name(value: str | None) -> str:
    normalized = _label_for_region_match(value or "").lower()
    normalized = re.sub(r"\s*\((country|state|territory)\)\s*$", "", normalized)
    normalized = re.sub(r"^the\s+", "", normalized)
    return " ".join(normalized.split())


def _regional_title_region_name(title: str | None) -> str | None:
    value = _label_for_region_match(title or "")
    patterns = (
        r"\bmusic\s+(?:in|of)\s+(?:the\s+)?(.+)$",
        r"\bpopular\s+music\s+of\s+(?:the\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            region_name = _normalized_region_match_name(match.group(1))
            if region_name:
                return region_name
    return None


def _promoted_region_title_matches_region(title: str | None, region_name: str | None) -> bool:
    normalized_region_name = _normalized_region_match_name(region_name)
    if not title or not normalized_region_name:
        return False
    candidates = (
        _region_name_from_music_title(title),
        _regional_title_region_name(title),
        _label_for_region_match(title),
    )
    return any(
        _normalized_region_match_name(candidate) == normalized_region_name
        for candidate in candidates
        if candidate
    )


def _map_item_from_region_row(row, *, map_key: str, match_type: str, role: str) -> MapRegionItemOut:
    region_name = row["canonical_name"] or row["region_name"]
    genre_id = row.get("genre_id")
    wikipedia_title = row.get("wikipedia_title")
    if (
        row.get("region_kind") != "country"
        and wikipedia_title
        and not _promoted_region_title_matches_region(wikipedia_title, region_name)
    ):
        genre_id = None
        wikipedia_title = None
    feature_key = _feature_key_for_region(region_name, map_key=map_key)
    display_title = row.get("display_title") or wikipedia_title or region_name
    return MapRegionItemOut(
        region_id=row["region_id"],
        region_key=_slug_region_key(region_name, fallback=row["region_id"]),
        region_name=region_name,
        region_kind=row.get("region_kind"),
        map_key=map_key,
        feature_key=feature_key,
        feature_name=feature_key,
        genre_id=genre_id,
        wikipedia_title=wikipedia_title,
        display_title=display_title,
        monthly_views_p30=row.get("monthly_views_p30"),
        similarity_color=row.get("similarity_color"),
        color_confidence=row.get("color_confidence"),
        match_type=match_type,
        selectable=True,
        role=role,
        selectable_for=display_title,
        selection_priority=0 if row.get("region_kind") == "country" else 5,
        represented_genre_ids=_represented_genre_ids(genre_id),
        represented_titles=_represented_titles(wikipedia_title, display_title, region_name),
    )


def _map_item_from_variant(item: RegionVariantOut, *, map_key: str) -> MapRegionItemOut:
    region_name = item.region_name
    feature_key = _feature_key_for_region(region_name, map_key=map_key)
    display_title = item.display_title or item.wikipedia_title
    return MapRegionItemOut(
        region_id=item.region_id,
        region_key=item.region_key,
        region_name=region_name,
        region_kind=item.region_kind,
        map_key=map_key,
        feature_key=feature_key,
        feature_name=feature_key,
        genre_id=item.genre_id,
        base_genre_id=item.base_genre_id,
        candidate_id=item.candidate_id,
        wikipedia_title=item.wikipedia_title,
        display_title=display_title,
        monthly_views_p30=item.monthly_views_p30,
        similarity_color=item.similarity_color,
        color_confidence=item.color_confidence,
        match_type=item.match_type,
        selectable=True,
        role="regional_variant"
        if item.match_type != "regional_style_candidate"
        else "regional_style_candidate",
        selectable_for=display_title,
        selection_priority=0 if item.region_kind == "country" else 5,
        represented_genre_ids=_represented_genre_ids(item.genre_id, item.base_genre_id),
        represented_titles=_represented_titles(
            item.wikipedia_title, item.display_title, region_name
        ),
    )


def _map_item_priority(item: MapRegionItemOut) -> tuple[int, int, str]:
    if item.selection_priority is not None:
        priority = item.selection_priority
    elif item.region_kind == "country":
        priority = 0
    else:
        priority = 50
    return (priority, -(item.monthly_views_p30 or 0), item.display_title.lower())


def _merge_map_item_represented(*items: MapRegionItemOut) -> tuple[list[str], list[str]]:
    genre_ids: list[str] = []
    titles: list[str] = []
    for item in items:
        for genre_id in [
            item.genre_id,
            item.base_genre_id,
            item.matched_genre_id,
            *item.represented_genre_ids,
        ]:
            if genre_id and genre_id not in genre_ids:
                genre_ids.append(genre_id)
        for title in [
            item.wikipedia_title,
            item.display_title,
            item.region_name,
            item.matched_region_name,
            *item.represented_titles,
        ]:
            if title and title not in titles:
                titles.append(title)
    return genre_ids, titles


def _map_item_with_represented(
    item: MapRegionItemOut, *others: MapRegionItemOut
) -> MapRegionItemOut:
    genre_ids, titles = _merge_map_item_represented(item, *others)
    represented_children: list[dict] = []
    seen_child_ids: set[str] = set()
    for source in (item, *others):
        for child in source.represented_children:
            child_id = child.get("genre_id")
            if child_id and child_id in seen_child_ids:
                continue
            if child_id:
                seen_child_ids.add(child_id)
            represented_children.append(child)
    return item.model_copy(
        update={
            "represented_genre_ids": genre_ids,
            "represented_titles": titles,
            "represented_children": represented_children,
        }
    )


def _dedupe_map_selectables(items: Iterable[MapRegionItemOut]) -> list[MapRegionItemOut]:
    best_by_feature: dict[tuple[str, str], MapRegionItemOut] = {}
    for item in items:
        item = _map_item_with_represented(item)
        feature = item.feature_key or item.region_key
        key = (item.map_key, feature)
        current = best_by_feature.get(key)
        if current is None:
            best_by_feature[key] = item
        elif _map_item_priority(item) < _map_item_priority(current):
            best_by_feature[key] = _map_item_with_represented(item, current)
        else:
            best_by_feature[key] = _map_item_with_represented(current, item)
    return sorted(
        best_by_feature.values(),
        key=lambda item: (
            item.feature_name or item.feature_key,
            _map_item_priority(item),
            item.display_title.lower(),
        ),
    )


async def _pure_region_matches_for_genre(
    session,
    *,
    genre_id: str,
    map_key: str,
) -> list[MapRegionItemOut]:
    rows = (
        (
            await session.execute(
                text("""
            SELECT DISTINCT ON (region.id)
                   region.id AS region_id,
                   region.canonical_name,
                   region.kind AS region_kind,
                   mapped.genre_id AS genre_id,
                   genre.wikipedia_title AS wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence,
                   mapped.confidence,
                   mapped.mapping_type
            FROM wg_region_node_mappings mapped
            JOIN wg_regions region ON region.id = mapped.region_id
            JOIN wg_genres genre ON genre.id = mapped.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = mapped.genre_id
            WHERE mapped.genre_id = :genre_id
              AND genre.deleted_at IS NULL
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY region.id, mapped.confidence DESC, mapped.mapping_type
        """),
                {"genre_id": genre_id},
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        _map_item_from_region_row(
            row,
            map_key=map_key,
            match_type="pure_region_match",
            role=row["region_kind"] or "region",
        )
        for row in rows
    ]


async def _pure_region_descendant_country_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE descendants(seed_region_id, region_id, depth, path) AS (
                SELECT rel.to_region_id,
                       rel.from_region_id,
                       1,
                       ARRAY[rel.to_region_id, rel.from_region_id]::text[]
                FROM wg_pure_region_relationships rel
                WHERE rel.to_region_id = ANY(:region_ids)
                UNION ALL
                SELECT descendants.seed_region_id,
                       rel.from_region_id,
                       descendants.depth + 1,
                       descendants.path || rel.from_region_id
                FROM descendants
                JOIN wg_pure_region_relationships rel
                  ON rel.to_region_id = descendants.region_id
                WHERE descendants.depth < 8
                  AND NOT rel.from_region_id = ANY(descendants.path)
            )
            SELECT DISTINCT ON (descendants.seed_region_id, country.id)
                   descendants.seed_region_id,
                   country.id AS country_region_id,
                   country.canonical_name AS country_name,
                   country.kind AS country_kind,
                   descendants.depth,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM descendants
            JOIN wg_regions country ON country.id = descendants.region_id
            LEFT JOIN wg_region_promoted_genres promoted ON promoted.region_id = country.id
            LEFT JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = promoted.genre_id
            WHERE country.kind = 'country'
              AND coalesce(country.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY descendants.seed_region_id,
                     country.id,
                     descendants.depth,
                     COALESCE(genre.monthly_views_p30, 0) DESC
        """),
                {"region_ids": region_ids},
            )
        )
        .mappings()
        .fetchall()
    )


async def _pure_region_country_ancestor_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_pure_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                UNION ALL
                SELECT ancestors.seed_region_id,
                       rel.to_region_id,
                       ancestors.depth + 1,
                       ancestors.path || rel.to_region_id
                FROM ancestors
                JOIN wg_pure_region_relationships rel
                  ON rel.from_region_id = ancestors.region_id
                WHERE ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(ancestors.path)
            )
            SELECT DISTINCT ON (ancestors.seed_region_id)
                   ancestors.seed_region_id,
                   country.id AS country_region_id,
                   country.canonical_name AS country_name,
                   country.kind AS country_kind,
                   ancestors.depth,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM ancestors
            JOIN wg_regions country ON country.id = ancestors.region_id
            LEFT JOIN wg_region_promoted_genres promoted ON promoted.region_id = country.id
            LEFT JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = promoted.genre_id
            WHERE country.kind = 'country'
              AND coalesce(country.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY ancestors.seed_region_id,
                     ancestors.depth,
                     COALESCE(genre.monthly_views_p30, 0) DESC
        """),
                {"region_ids": region_ids},
            )
        )
        .mappings()
        .fetchall()
    )


async def _pure_region_group_ancestor_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_pure_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                UNION ALL
                SELECT ancestors.seed_region_id,
                       rel.to_region_id,
                       ancestors.depth + 1,
                       ancestors.path || rel.to_region_id
                FROM ancestors
                JOIN wg_pure_region_relationships rel
                  ON rel.from_region_id = ancestors.region_id
                WHERE ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(ancestors.path)
            )
            SELECT DISTINCT ON (ancestors.seed_region_id)
                   ancestors.seed_region_id,
                   region.id AS group_region_id,
                   region.canonical_name AS group_region_name,
                   region.kind AS group_region_kind,
                   ancestors.depth
            FROM ancestors
            JOIN wg_regions region ON region.id = ancestors.region_id
            WHERE region.kind NOT IN ('country', 'territory', 'subregion')
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY ancestors.seed_region_id,
                     CASE
                       WHEN region.kind = 'superregion' THEN 0
                       WHEN region.kind = 'continent' THEN 1
                       ELSE 2
                     END,
                     ancestors.depth,
                     region.canonical_name
        """),
                {"region_ids": region_ids},
            )
        )
        .mappings()
        .fetchall()
    )


async def _region_country_ancestor_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                  AND rel.status = 'accepted'
                UNION ALL
                SELECT ancestors.seed_region_id,
                       rel.to_region_id,
                       ancestors.depth + 1,
                       ancestors.path || rel.to_region_id
                FROM ancestors
                JOIN wg_region_relationships rel
                  ON rel.from_region_id = ancestors.region_id
                WHERE rel.status = 'accepted'
                  AND ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(ancestors.path)
            )
            SELECT DISTINCT ON (ancestors.seed_region_id)
                   ancestors.seed_region_id,
                   country.id AS country_region_id,
                   country.canonical_name AS country_name,
                   country.kind AS country_kind,
                   ancestors.depth
            FROM ancestors
            JOIN wg_regions country ON country.id = ancestors.region_id
            WHERE country.kind = 'country'
              AND coalesce(country.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY ancestors.seed_region_id,
                     ancestors.depth,
                     country.canonical_name
        """),
                {"region_ids": region_ids},
            )
        )
        .mappings()
        .fetchall()
    )


async def _region_rows_by_canonical_names(session, region_names: list[str]):
    if not region_names:
        return []
    return (
        (
            await session.execute(
                text("""
            SELECT region.id,
                   region.canonical_name,
                   region.kind
            FROM wg_regions region
            WHERE lower(region.canonical_name) = ANY(:region_names)
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
        """),
                {"region_names": region_names},
            )
        )
        .mappings()
        .fetchall()
    )


async def _region_group_ancestor_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                  AND rel.status = 'accepted'
                UNION ALL
                SELECT ancestors.seed_region_id,
                       rel.to_region_id,
                       ancestors.depth + 1,
                       ancestors.path || rel.to_region_id
                FROM ancestors
                JOIN wg_region_relationships rel
                  ON rel.from_region_id = ancestors.region_id
                WHERE rel.status = 'accepted'
                  AND ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(ancestors.path)
            )
            SELECT DISTINCT ON (ancestors.seed_region_id)
                   ancestors.seed_region_id,
                   region.id AS group_region_id,
                   region.canonical_name AS group_region_name,
                   region.kind AS group_region_kind,
                   ancestors.depth
            FROM ancestors
            JOIN wg_regions region ON region.id = ancestors.region_id
            WHERE region.kind NOT IN ('country', 'territory', 'subregion')
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY ancestors.seed_region_id,
                     CASE
                       WHEN region.kind = 'superregion' THEN 0
                       WHEN region.kind = 'continent' THEN 1
                       ELSE 2
                     END,
                     ancestors.depth,
                     region.canonical_name
        """),
                {"region_ids": region_ids},
            )
        )
        .mappings()
        .fetchall()
    )


async def _root_continent_group_rows(session, region_ids: list[str]):
    if not region_ids:
        return []
    return (
        (
            await session.execute(
                text("""
            WITH RECURSIVE accepted_ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                  AND rel.status = 'accepted'
                UNION ALL
                SELECT accepted_ancestors.seed_region_id,
                       rel.to_region_id,
                       accepted_ancestors.depth + 1,
                       accepted_ancestors.path || rel.to_region_id
                FROM accepted_ancestors
                JOIN wg_region_relationships rel
                  ON rel.from_region_id = accepted_ancestors.region_id
                WHERE rel.status = 'accepted'
                  AND accepted_ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(accepted_ancestors.path)
            ),
            pure_ancestors(seed_region_id, region_id, depth, path) AS (
                SELECT rel.from_region_id,
                       rel.to_region_id,
                       1,
                       ARRAY[rel.from_region_id, rel.to_region_id]::text[]
                FROM wg_pure_region_relationships rel
                WHERE rel.from_region_id = ANY(:region_ids)
                UNION ALL
                SELECT pure_ancestors.seed_region_id,
                       rel.to_region_id,
                       pure_ancestors.depth + 1,
                       pure_ancestors.path || rel.to_region_id
                FROM pure_ancestors
                JOIN wg_pure_region_relationships rel
                  ON rel.from_region_id = pure_ancestors.region_id
                WHERE pure_ancestors.depth < 8
                  AND NOT rel.to_region_id = ANY(pure_ancestors.path)
            ),
            ancestors AS (
                SELECT seed_region_id, region_id, depth, 0 AS source_rank
                FROM accepted_ancestors
                UNION ALL
                SELECT seed_region_id, region_id, depth, 1 AS source_rank
                FROM pure_ancestors
            )
            SELECT DISTINCT ON (ancestors.seed_region_id)
                   ancestors.seed_region_id,
                   region.id AS group_region_id,
                   region.canonical_name AS group_region_name,
                   'continent' AS group_region_kind,
                   ancestors.depth
            FROM ancestors
            JOIN wg_regions region ON region.id = ancestors.region_id
            WHERE region.canonical_name = ANY(:continent_names)
              AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
            ORDER BY ancestors.seed_region_id,
                     CASE WHEN region.canonical_name = 'Americas' THEN 1 ELSE 0 END,
                     ancestors.depth,
                     CASE region.canonical_name
                       WHEN 'North America' THEN 0
                       WHEN 'South America' THEN 1
                       ELSE 2
                     END,
                     ancestors.source_rank,
                     region.canonical_name
        """),
                {
                    "region_ids": region_ids,
                    "continent_names": list(ROOT_LIST_CONTINENT_NAMES),
                },
            )
        )
        .mappings()
        .fetchall()
    )


async def _annotate_root_map_items_for_list(
    session,
    items: list[MapRegionItemOut],
) -> list[MapRegionItemOut]:
    region_ids = sorted({item.region_id for item in items if item.region_id})
    group_by_region = {
        row["seed_region_id"]: row for row in await _root_continent_group_rows(session, region_ids)
    }
    return [
        item.model_copy(
            update={
                "list_group_region_id": group_by_region[item.region_id]["group_region_id"],
                "list_group_region_name": group_by_region[item.region_id]["group_region_name"],
                "list_group_region_kind": group_by_region[item.region_id]["group_region_kind"],
            }
        )
        if item.region_id in group_by_region
        else item
        for item in items
    ]


async def _annotate_map_items_for_list(
    session,
    items: list[MapRegionItemOut],
    *,
    map_key: str,
) -> list[MapRegionItemOut]:
    if not items:
        return items

    unresolved_region_names = sorted(
        {
            item.region_name.strip().casefold()
            for item in items
            if item.region_name and not item.region_id
        }
    )
    resolved_region_rows = await _region_rows_by_canonical_names(session, unresolved_region_names)
    resolved_region_by_name = {
        row["canonical_name"].casefold(): row for row in resolved_region_rows
    }

    resolved_region_by_item: dict[int, dict[str, Any]] = {}
    region_ids: list[str] = []
    seen_region_ids: set[str] = set()
    for item in items:
        resolved_region = None
        if item.region_name and not item.region_id:
            resolved_region = resolved_region_by_name.get(item.region_name.strip().casefold())
        effective_region_id = item.region_id or (resolved_region and resolved_region["id"])
        if resolved_region is not None:
            resolved_region_by_item[id(item)] = resolved_region
        if effective_region_id and effective_region_id not in seen_region_ids:
            seen_region_ids.add(effective_region_id)
            region_ids.append(effective_region_id)

    descendant_rows = await _pure_region_descendant_country_rows(session, region_ids)
    country_ancestor_rows = await _pure_region_country_ancestor_rows(session, region_ids)
    direct_country_ancestor_rows = await _region_country_ancestor_rows(session, region_ids)
    group_rows = await _pure_region_group_ancestor_rows(session, region_ids)
    direct_group_rows = await _region_group_ancestor_rows(session, region_ids)

    descendant_keys_by_region: dict[str, list[str]] = {}
    for row in descendant_rows:
        key = _feature_key_for_region(row["country_name"], map_key=WORLD_MAP_KEY)
        existing = descendant_keys_by_region.setdefault(row["seed_region_id"], [])
        if key not in existing:
            existing.append(key)

    country_ancestor_by_region = {row["seed_region_id"]: row for row in country_ancestor_rows}
    country_ancestor_by_region.update(
        {row["seed_region_id"]: row for row in direct_country_ancestor_rows}
    )
    group_by_region = {row["seed_region_id"]: row for row in group_rows}
    group_by_region.update({row["seed_region_id"]: row for row in direct_group_rows})

    annotated: list[MapRegionItemOut] = []
    for item in items:
        resolved_region = resolved_region_by_item.get(id(item))
        effective_region_id = item.region_id or (resolved_region and resolved_region["id"])
        effective_region_name = item.region_name or (
            resolved_region and resolved_region["canonical_name"]
        )
        effective_region_kind = item.region_kind or (resolved_region and resolved_region["kind"])
        icon_feature_keys: list[str] = []
        if map_key == US_MAP_KEY:
            icon_feature_keys = [_feature_key_for_region("United States", map_key=WORLD_MAP_KEY)]
        elif (
            effective_region_id
            and effective_region_id in descendant_keys_by_region
            and effective_region_kind != "country"
        ):
            icon_feature_keys = descendant_keys_by_region[effective_region_id]
        elif (
            effective_region_kind != "country"
            and effective_region_id
            and effective_region_id in country_ancestor_by_region
        ):
            icon_feature_keys = [
                _feature_key_for_region(
                    country_ancestor_by_region[effective_region_id]["country_name"],
                    map_key=WORLD_MAP_KEY,
                )
            ]
        elif item.feature_key:
            icon_feature_keys = [item.feature_key]

        group = (
            (effective_region_id and group_by_region.get(effective_region_id))
            or (item.mount_parent_region_id and group_by_region.get(item.mount_parent_region_id))
            or (item.matched_region_id and group_by_region.get(item.matched_region_id))
        )
        if (
            group is None
            and effective_region_kind not in ("country", "territory", "subregion")
            and effective_region_id
        ):
            group = {
                "group_region_id": effective_region_id,
                "group_region_name": effective_region_name,
                "group_region_kind": effective_region_kind,
            }

        annotated.append(
            item.model_copy(
                update={
                    "region_id": effective_region_id,
                    "region_name": effective_region_name,
                    "region_kind": effective_region_kind,
                    "list_group_region_id": group["group_region_id"] if group else None,
                    "list_group_region_name": group["group_region_name"] if group else None,
                    "list_group_region_kind": group["group_region_kind"] if group else None,
                    "icon_feature_keys": icon_feature_keys,
                }
            )
        )

    return annotated


async def _expand_map_items_with_pure_region_graph(
    session,
    items: list[MapRegionItemOut],
    *,
    map_key: str,
) -> list[MapRegionItemOut]:
    by_region_id = {item.region_id: item for item in items if item.region_id}
    seed_region_ids = list(by_region_id)
    if not seed_region_ids:
        return _dedupe_map_selectables(items)

    expanded: list[MapRegionItemOut] = list(items)
    superregion_parent_by_country: dict[str, MapRegionItemOut] = {}
    directly_mapped_country_genres = {
        item.genre_id
        for item in items
        if item.genre_id and item.region_kind in ("country", "territory")
    }

    descendants = await _pure_region_descendant_country_rows(session, seed_region_ids)
    descendant_seed_ids = {row["seed_region_id"] for row in descendants}
    for row in descendants:
        source = by_region_id.get(row["seed_region_id"])
        if source is None or source.region_kind == "country":
            continue
        if source.genre_id and source.genre_id in directly_mapped_country_genres:
            continue
        country_name = row["country_name"]
        feature_key = _feature_key_for_region(country_name, map_key=map_key)
        display_title = source.display_title or source.region_name or country_name
        superregion_parent_by_country.setdefault(row["country_region_id"], source)
        expanded.append(
            MapRegionItemOut(
                region_id=row["country_region_id"],
                region_key=_slug_region_key(country_name, fallback=row["country_region_id"]),
                region_name=country_name,
                region_kind="country",
                map_key=map_key,
                feature_key=feature_key,
                feature_name=feature_key,
                genre_id=source.genre_id,
                wikipedia_title=source.wikipedia_title,
                display_title=display_title,
                monthly_views_p30=source.monthly_views_p30,
                similarity_color=source.similarity_color,
                color_confidence=source.color_confidence,
                match_type="pure_region_descendant_country",
                selectable=True,
                role="country",
                selectable_for=_selectable_for_label(country_name, source),
                matched_region_id=source.region_id,
                matched_region_name=source.region_name,
                matched_region_kind=source.region_kind,
                matched_genre_id=source.genre_id,
                mount_parent_region_id=source.region_id,
                mount_parent_region_name=source.region_name,
                selection_priority=20,
                represented_genre_ids=_represented_genre_ids(source.genre_id),
                represented_titles=_represented_titles(source.wikipedia_title, display_title),
            )
        )

    child_seed_ids = [
        region_id
        for region_id, item in by_region_id.items()
        if item.region_kind != "country" and region_id not in descendant_seed_ids
    ]
    ancestors = await _pure_region_country_ancestor_rows(session, child_seed_ids)
    for row in ancestors:
        source = by_region_id.get(row["seed_region_id"])
        if source is None:
            continue
        country_name = row["country_name"]
        feature_key = _feature_key_for_region(country_name, map_key=map_key)
        expanded.append(
            source.model_copy(
                update={
                    "map_key": map_key,
                    "feature_key": feature_key,
                    "feature_name": feature_key,
                    "match_type": "pure_region_child_country",
                    "selectable_for": _selectable_for_label(country_name, source),
                    "matched_region_id": source.region_id,
                    "matched_region_name": source.region_name,
                    "matched_region_kind": source.region_kind,
                    "matched_genre_id": source.genre_id,
                    "mount_parent_region_id": row["country_region_id"],
                    "mount_parent_region_name": country_name,
                    "selection_priority": 10,
                }
            )
        )

    reparented: list[MapRegionItemOut] = []
    for item in expanded:
        if item.region_kind == "country" and item.region_id in superregion_parent_by_country:
            parent = superregion_parent_by_country[item.region_id]
            reparented.append(
                item.model_copy(
                    update={
                        "mount_parent_region_id": item.mount_parent_region_id or parent.region_id,
                        "mount_parent_region_name": item.mount_parent_region_name
                        or parent.region_name,
                        "matched_region_id": item.matched_region_id or parent.region_id,
                        "matched_region_name": item.matched_region_name or parent.region_name,
                        "matched_region_kind": item.matched_region_kind or parent.region_kind,
                        "matched_genre_id": item.matched_genre_id or parent.genre_id,
                    }
                )
            )
        else:
            reparented.append(item)
    return _dedupe_map_selectables(reparented)


async def _direct_regional_child_rows_for_map(session, *, genre_id: str):
    return (
        (
            await session.execute(
                text("""
            SELECT DISTINCT ON (child_g.id)
                   child_g.id AS genre_id,
                   child_g.wikipedia_title,
                   child_g.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence,
                   e.relation,
                   e.evidence_relation
            FROM wg_relationship_traversal_edges e
            JOIN wg_genres child_g ON child_g.id = e.to_genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = child_g.id
            WHERE e.from_genre_id = :genre_id
              AND e.to_genre_id IS NOT NULL
              AND e.is_ignored = false
              AND child_g.deleted_at IS NULL
              AND child_g.is_non_genre = false
              AND (
                e.relation = ANY(:variant_relations)
                OR (
                  e.relation = :related_relation
                  AND e.evidence_relation = ANY(:variant_evidence_relations)
                )
              )
            ORDER BY child_g.id,
                     COALESCE(child_g.monthly_views_p30, 0) DESC,
                     e.relation
        """),
                {
                    "genre_id": genre_id,
                    "variant_relations": list(MAP_VARIANT_RELATIONS),
                    "variant_evidence_relations": list(MAP_VARIANT_EVIDENCE_RELATIONS),
                    "related_relation": RELATED_RELATION,
                },
            )
        )
        .mappings()
        .fetchall()
    )


def _represented_child_from_row(row) -> dict:
    return {
        "genre_id": row["genre_id"],
        "wikipedia_title": row["wikipedia_title"],
        "display_title": row["wikipedia_title"],
        "monthly_views_p30": row["monthly_views_p30"],
        "similarity_color": row["similarity_color"],
        "color_confidence": row["color_confidence"],
        "relation": row["evidence_relation"] or row["relation"] or "regional_variant",
    }


async def _group_country_map_items_with_regional_children(
    session,
    *,
    parent_genre_id: str,
    parent_title: str,
    items: list[MapRegionItemOut],
) -> list[MapRegionItemOut]:
    if not items:
        return items
    child_rows = await _direct_regional_child_rows_for_map(session, genre_id=parent_genre_id)
    if not child_rows:
        return items

    item_by_genre_id: dict[str, MapRegionItemOut] = {}
    item_by_region_name: dict[str, MapRegionItemOut] = {}
    for item in items:
        for genre_id in [item.genre_id, *item.represented_genre_ids]:
            if genre_id:
                item_by_genre_id.setdefault(genre_id, item)
        for region_name in [item.region_name, item.feature_name, item.feature_key]:
            normalized = _normalized_region_match_name(region_name)
            if normalized:
                item_by_region_name.setdefault(normalized, item)

    children_by_feature: dict[tuple[str, str], dict[str, dict]] = {}
    for row in child_rows:
        item = item_by_genre_id.get(row["genre_id"])
        if item is None:
            region_name = _regional_title_region_name(row["wikipedia_title"])
            if region_name:
                item = item_by_region_name.get(region_name)
        if item is None:
            continue
        key = (item.map_key, item.feature_key or item.region_key)
        children_by_feature.setdefault(key, {})[row["genre_id"]] = _represented_child_from_row(row)

    if not children_by_feature:
        return items

    grouped_items: list[MapRegionItemOut] = []
    parent_label = _label_for_region_match(parent_title)
    for item in items:
        key = (item.map_key, item.feature_key or item.region_key)
        children = list(children_by_feature.get(key, {}).values())
        if not children:
            grouped_items.append(item)
            continue
        children.sort(
            key=lambda child: (
                -(child.get("monthly_views_p30") or 0),
                child.get("wikipedia_title") or "",
            )
        )
        child_genre_ids = _represented_genre_ids(*(child.get("genre_id") for child in children))
        child_titles = _represented_titles(*(child.get("wikipedia_title") for child in children))
        if len(children) == 1 or (
            item.genre_id
            and any(child.get("genre_id") == item.genre_id for child in children)
        ):
            grouped_items.append(
                item.model_copy(
                    update={
                        "represented_genre_ids": _represented_genre_ids(
                            *item.represented_genre_ids,
                            *child_genre_ids,
                        ),
                        "represented_titles": _represented_titles(
                            *item.represented_titles,
                            *child_titles,
                        ),
                        "represented_children": children,
                    }
                )
            )
            continue

        display_title = f"{parent_label} in {item.region_name}"
        grouped_items.append(
            item.model_copy(
                update={
                    "genre_id": None,
                    "base_genre_id": parent_genre_id,
                    "candidate_id": None,
                    "wikipedia_title": None,
                    "display_title": display_title,
                    "match_type": "inferred_country_region_group",
                    "role": "country_region_group",
                    "selectable_for": display_title,
                    "selection_priority": -1,
                    "represented_genre_ids": child_genre_ids,
                    "represented_titles": child_titles,
                    "represented_children": children,
                }
            )
        )

    return grouped_items


def _region_name_from_music_title(title: str) -> str | None:
    match = re.match(r"^music of (?:the )?(.+)$", title.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    name = re.sub(r"\s*\(country\)\s*$", "", match.group(1), flags=re.IGNORECASE).strip()
    return " ".join(name.split()) or None


def _known_region_for_music_title(title: str) -> Region | None:
    title_lower = title.lower()
    for region in REGIONS:
        known_titles = {
            f"music of {str(region['of']).lower()}",
            f"music of {str(region['name']).lower()}",
        }
        if title_lower in known_titles:
            return region
    return None


def _region_name_from_regional_title(title: str | None) -> str | None:
    if not title:
        return None
    region = _known_region_for_music_title(title)
    if region:
        return region["name"]
    explicit_region_name = _regional_title_region_name(title) or _region_name_from_music_title(
        title
    )
    if explicit_region_name:
        return explicit_region_name
    label = _label_for_region_match(title).lower()
    for region in REGIONS:
        names = {str(region["name"]).lower(), str(region["of"]).lower()}
        for name in names:
            if label.startswith(f"{name} ") or f" in {name}" in label or f" of {name}" in label:
                return region["name"]
        for demonym in region["demonyms"]:
            demonym_lower = str(demonym).lower()
            if label.startswith(f"{demonym_lower} "):
                return region["name"]
    return None


def _variant_from_music_region_row(row, *, match_type: str) -> RegionVariantOut | None:
    title = row["wikipedia_title"]
    region = _known_region_for_music_title(title)
    region_name = region["name"] if region else _region_name_from_music_title(title)
    if not region_name:
        return None
    return RegionVariantOut(
        region_key=region["key"] if region else _slug_region_key(region_name, fallback=row["id"]),
        region_name=region_name,
        region_id=row.get("region_id"),
        region_kind=row.get("region_kind"),
        x=region["x"] if region else None,
        y=region["y"] if region else None,
        genre_id=row["id"],
        wikipedia_title=title,
        display_title=title,
        monthly_views_p30=row["monthly_views_p30"],
        similarity_color=row["similarity_color"],
        color_confidence=row["color_confidence"],
        match_type=match_type,
    )


def _variant_from_regional_child_row(row, *, match_type: str) -> RegionVariantOut | None:
    region_title = row["region_title"]
    region = _known_region_for_music_title(region_title)
    region_name = region["name"] if region else _region_name_from_music_title(region_title)
    if not region_name:
        return None
    child_region_name = _region_name_from_regional_title(row["wikipedia_title"])
    if child_region_name and _normalized_region_match_name(
        child_region_name
    ) != _normalized_region_match_name(region_name):
        return None
    return RegionVariantOut(
        region_key=region["key"] if region else _slug_region_key(region_name, fallback=row["id"]),
        region_name=region_name,
        region_id=row.get("region_id"),
        region_kind=row.get("region_kind"),
        x=region["x"] if region else None,
        y=region["y"] if region else None,
        genre_id=row["id"],
        wikipedia_title=row["wikipedia_title"],
        display_title=row["wikipedia_title"],
        monthly_views_p30=row["monthly_views_p30"],
        similarity_color=row["similarity_color"],
        color_confidence=row["color_confidence"],
        match_type=match_type,
    )


def _regional_graph_region_rank(row) -> int:
    kind = row.get("region_kind")
    if kind in ("country", "territory"):
        return 0
    if kind in ("subregion", "city"):
        return 1
    if kind in ("cultural_region", "historical_region"):
        return 2
    if kind == "continent":
        return 3
    return 4


def _most_specific_regional_graph_rows(rows):
    best_rank_by_child: dict[str, int] = {}
    for row in rows:
        child_id = row["id"]
        rank = _regional_graph_region_rank(row)
        best_rank_by_child[child_id] = min(rank, best_rank_by_child.get(child_id, rank))
    return [
        row
        for row in rows
        if _regional_graph_region_rank(row) == best_rank_by_child.get(row["id"])
    ]


async def _regional_variants_for_title(
    session,
    *,
    genre_id: str | None,
    title: str,
    root_mode: bool = False,
) -> RegionVariantsResult:
    candidate_to_region: dict[str, tuple[Region, str]] = {}
    items: list[RegionVariantOut] = []

    if root_mode:
        rows = (
            (
                await session.execute(
                    text("""
                SELECT g.id,
                       g.wikipedia_title,
                       g.monthly_views_p30,
                       c.color_hex AS similarity_color,
                       c.confidence AS color_confidence,
                       region.id AS region_id,
                       region.kind AS region_kind
                FROM wg_genres g
                LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                JOIN wg_region_promoted_genres promoted ON promoted.genre_id = g.id
                JOIN wg_regions region ON region.id = promoted.region_id
                WHERE g.deleted_at IS NULL
                  AND g.is_non_genre = false
                  AND g.wikipedia_title ILIKE 'Music of %'
                  AND region.kind = 'country'
                ORDER BY g.wikipedia_title
            """),
                )
            )
            .mappings()
            .fetchall()
        )
        for row in rows:
            item = _variant_from_music_region_row(row, match_type="music_region")
            if item:
                items.append(item)
        items.sort(key=lambda item: (item.region_name, item.wikipedia_title))
        return RegionVariantsResult(genre_id=genre_id, wikipedia_title=title, items=items)

    for region in REGIONS:
        for candidate in _regional_title_candidates(title, region):
            candidate_to_region[candidate] = (region, "regional_variant")

    if candidate_to_region:
        rows = (
            (
                await session.execute(
                    text("""
                SELECT g.id,
                       g.wikipedia_title,
                       g.monthly_views_p30,
                       c.color_hex AS similarity_color,
                       c.confidence AS color_confidence
                FROM wg_genres g
                LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                WHERE g.deleted_at IS NULL
                  AND g.is_non_genre = false
                  AND lower(g.wikipedia_title) = ANY(:titles)
            """),
                    {"titles": list(candidate_to_region.keys())},
                )
            )
            .mappings()
            .fetchall()
        )

        rows = sorted(
            rows,
            key=lambda row: (-(row["monthly_views_p30"] or 0), row["wikipedia_title"].lower()),
        )
        for row in rows:
            region, match_type = candidate_to_region[row["wikipedia_title"].lower()]
            items.append(
                RegionVariantOut(
                    region_key=region["key"],
                    region_name=region["name"],
                    x=region["x"],
                    y=region["y"],
                    genre_id=row["id"],
                    wikipedia_title=row["wikipedia_title"],
                    monthly_views_p30=row["monthly_views_p30"],
                    similarity_color=row["similarity_color"],
                    color_confidence=row["color_confidence"],
                    match_type=match_type,
                )
            )

    if genre_id:
        graph_rows = (
            (
                await session.execute(
                    text("""
                WITH selected_children AS (
                    SELECT DISTINCT e.to_genre_id AS child_id
                    FROM wg_relationship_traversal_edges e
                    JOIN wg_genres child_g ON child_g.id = e.to_genre_id
                    WHERE e.from_genre_id = :genre_id
                      AND e.to_genre_id IS NOT NULL
                      AND e.is_ignored = false
                      AND child_g.deleted_at IS NULL
                      AND child_g.is_non_genre = false
                      AND (
                        e.relation = ANY(:variant_relations)
                        OR (
                          e.relation = :related_relation
                          AND e.evidence_relation = ANY(:variant_evidence_relations)
                        )
                      )
                ),
                region_links AS (
                    SELECT DISTINCT region_g.id AS region_genre_id,
                           region_g.wikipedia_title AS region_title,
                           region.id AS region_id,
                           region.kind AS region_kind,
                           child_g.id,
                           child_g.wikipedia_title,
                           child_g.monthly_views_p30,
                           c.color_hex AS similarity_color,
                           c.confidence AS color_confidence
                    FROM selected_children sc
                    JOIN wg_relationship_traversal_edges re ON re.to_genre_id = sc.child_id
                    JOIN wg_genres region_g ON region_g.id = re.from_genre_id
                    LEFT JOIN wg_region_promoted_genres promoted_region
                      ON promoted_region.genre_id = region_g.id
                    LEFT JOIN wg_regions region ON region.id = promoted_region.region_id
                    JOIN wg_genres child_g ON child_g.id = sc.child_id
                    LEFT JOIN wg_genre_colors c ON c.genre_id = child_g.id
                    WHERE re.is_ignored = false
                      AND region_g.deleted_at IS NULL
                      AND region_g.is_non_genre = false
                      AND region_g.wikipedia_title ILIKE 'Music of %'
                      AND (
                        re.relation = ANY(:region_parent_relations)
                        OR (
                          re.relation = :related_relation
                          AND re.evidence_relation = ANY(:region_parent_evidence_relations)
                        )
                      )
                    UNION
                    SELECT DISTINCT region_g.id AS region_genre_id,
                           region_g.wikipedia_title AS region_title,
                           region.id AS region_id,
                           region.kind AS region_kind,
                           child_g.id,
                           child_g.wikipedia_title,
                           child_g.monthly_views_p30,
                           c.color_hex AS similarity_color,
                           c.confidence AS color_confidence
                    FROM selected_children sc
                    JOIN wg_relationship_traversal_edges re ON re.from_genre_id = sc.child_id
                    JOIN wg_genres region_g ON region_g.id = re.to_genre_id
                    LEFT JOIN wg_region_promoted_genres promoted_region
                      ON promoted_region.genre_id = region_g.id
                    LEFT JOIN wg_regions region ON region.id = promoted_region.region_id
                    JOIN wg_genres child_g ON child_g.id = sc.child_id
                    LEFT JOIN wg_genre_colors c ON c.genre_id = child_g.id
                    WHERE re.is_ignored = false
                      AND region_g.deleted_at IS NULL
                      AND region_g.is_non_genre = false
                      AND region_g.wikipedia_title ILIKE 'Music of %'
                      AND (
                        re.relation = ANY(:region_parent_relations)
                        OR (
                          re.relation = :related_relation
                          AND re.evidence_relation = ANY(:region_parent_evidence_relations)
                        )
                      )
                )
                SELECT *
                FROM region_links
                ORDER BY COALESCE(monthly_views_p30, 0) DESC, wikipedia_title, region_title
            """),
                    {
                        "genre_id": genre_id,
                        "variant_relations": list(MAP_VARIANT_RELATIONS),
                        "variant_evidence_relations": list(MAP_VARIANT_EVIDENCE_RELATIONS),
                        "region_parent_evidence_relations": [
                            *DISPLAY_RELATIONS,
                            REGIONAL_SCENE_EVIDENCE_RELATION,
                        ],
                        "region_parent_relations": list(REGION_PARENT_RELATIONS),
                        "related_relation": RELATED_RELATION,
                    },
                )
            )
            .mappings()
            .fetchall()
        )
        graph_rows = _most_specific_regional_graph_rows(graph_rows)
        for row in graph_rows:
            item = _variant_from_regional_child_row(row, match_type="regional_graph")
            if item:
                items.append(item)

        inferred_rows = (
            (
                await session.execute(
                    text("""
                SELECT inferred.id AS candidate_id,
                       inferred.base_genre_id,
                       inferred.proposed_display_title,
                       inferred.confidence,
                       region.id AS region_id,
                       region.canonical_name AS region_name,
                       region.kind AS region_kind,
                       base_g.monthly_views_p30,
                       c.color_hex AS similarity_color,
                       c.confidence AS color_confidence
                FROM wg_region_inferred_genres inferred
                JOIN wg_regions region ON region.id = inferred.region_id
                JOIN wg_genres base_g ON base_g.id = inferred.base_genre_id
                LEFT JOIN wg_genre_colors c ON c.genre_id = inferred.base_genre_id
                WHERE inferred.base_genre_id = :genre_id
                  AND inferred.status IN ('proposed', 'accepted')
                  AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                    'collapsed',
                    'rejected',
                    'demoted_source',
                    'hidden_from_ui'
                  )
                ORDER BY inferred.confidence DESC,
                         region.canonical_name,
                         inferred.proposed_display_title
            """),
                    {"genre_id": genre_id},
                )
            )
            .mappings()
            .fetchall()
        )
        for row in inferred_rows:
            region_name = row["region_name"]
            items.append(
                RegionVariantOut(
                    region_key=_slug_region_key(region_name, fallback=row["region_id"]),
                    region_name=region_name,
                    region_id=row["region_id"],
                    region_kind=row["region_kind"],
                    genre_id=None,
                    base_genre_id=row["base_genre_id"],
                    candidate_id=row["candidate_id"],
                    wikipedia_title=row["proposed_display_title"],
                    display_title=row["proposed_display_title"],
                    monthly_views_p30=row["monthly_views_p30"],
                    similarity_color=row["similarity_color"],
                    color_confidence=row["color_confidence"],
                    match_type="regional_style_candidate",
                )
            )

    seen_variants: set[tuple[str, str | None, str | None]] = set()
    deduped: list[RegionVariantOut] = []
    items.sort(
        key=lambda item: (
            -(item.monthly_views_p30 or 0),
            item.match_type != "regional_graph",
            item.wikipedia_title.lower(),
        )
    )
    for item in items:
        key = (item.region_key, item.genre_id, item.candidate_id)
        if key in seen_variants:
            continue
        seen_variants.add(key)
        deduped.append(item)
    items = deduped
    items.sort(key=lambda item: (item.region_name, item.wikipedia_title))
    return RegionVariantsResult(genre_id=genre_id, wikipedia_title=title, items=items)


# ------------------------------------------------------------------ #
# GET /v1/genres                                                      #
# ------------------------------------------------------------------ #


@router.get("", response_model=PaginatedGenres)
async def list_genres(
    q: str | None = Query(None, description="Filter by title substring (case-insensitive)."),
    has_infobox: bool | None = Query(None),
    updated_since: str | None = Query(None, description="ISO 8601 timestamp."),
    include_deleted: bool = Query(False, description="Include soft-deleted genres."),
    sort_by: str = Query(
        "title",
        pattern="^(title|views)$",
        description="Sort by title or monthly views.",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> PaginatedGenres:
    """Paginated list of genres with optional filters."""
    offset = (page - 1) * size
    conditions: list[str] = []
    params: dict = {"limit": size, "offset": offset}

    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    conditions.append("is_non_genre = false")
    if q:
        conditions.append("wikipedia_title ILIKE :q")
        params["q"] = f"%{q}%"
    if has_infobox is not None:
        conditions.append("has_infobox = :has_infobox")
        params["has_infobox"] = has_infobox
    if updated_since:
        conditions.append("last_changed_at >= :since")
        params["since"] = updated_since

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    list_where = (
        "WHERE "
        + " AND ".join(
            condition.replace("deleted_at", "g.deleted_at")
            .replace("is_non_genre", "g.is_non_genre")
            .replace("wikipedia_title", "g.wikipedia_title")
            .replace("has_infobox", "g.has_infobox")
            .replace("last_changed_at", "g.last_changed_at")
            for condition in conditions
        )
        if conditions
        else ""
    )
    order = (
        "ORDER BY g.monthly_views_p30 DESC NULLS LAST, g.wikipedia_title"
        if sort_by == "views"
        else "ORDER BY g.wikipedia_title"
    )

    async with session_scope() as session:
        total = (
            await session.scalar(
                text(f"SELECT count(*) FROM wg_genres {where}"),
                params,
            )
        ) or 0

        rows = (
            (
                await session.execute(
                    text(f"""
                SELECT g.id, g.wikidata_qid, g.wikipedia_title, g.wikipedia_url,
                       g.has_infobox, g.infobox_color, g.summary,
                       g.last_changed_at, g.last_fetched_at, g.monthly_views_p30,
                       c.color_hex AS similarity_color,
                       c.confidence AS color_confidence
                FROM wg_genres g
                LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                {list_where}
                {order}
                LIMIT :limit OFFSET :offset
            """),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

    return PaginatedGenres(
        items=[GenreListItem(**dict(r)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
    )


# ------------------------------------------------------------------ #
# GET /v1/genres/cloud                                                #
# ------------------------------------------------------------------ #


async def _region_cloud_rows(session, *, region_id: str):
    rows = (
        (
            await session.execute(
                text("""
                    WITH RECURSIVE region_tree AS (
                        SELECT
                            region.id AS region_id,
                            region.canonical_name,
                            region.kind,
                            promoted.genre_id AS promoted_genre_id,
                            promoted.wikipedia_title AS promoted_title,
                            0 AS region_depth
                        FROM wg_regions region
                        JOIN wg_region_promoted_genres promoted ON promoted.region_id = region.id
                        WHERE region.id = :region_id

                        UNION ALL

                        SELECT
                            child.id AS region_id,
                            child.canonical_name,
                            child.kind,
                            promoted.genre_id AS promoted_genre_id,
                            promoted.wikipedia_title AS promoted_title,
                            parent.region_depth + 1 AS region_depth
                        FROM region_tree parent
                        JOIN wg_region_relationships rel ON rel.to_region_id = parent.region_id
                        JOIN wg_regions child ON child.id = rel.from_region_id
                        JOIN wg_region_promoted_genres promoted ON promoted.region_id = child.id
                        WHERE rel.status = 'accepted'
                          AND parent.region_depth < 4
                          AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                              'collapsed',
                              'rejected',
                              'demoted_source',
                              'hidden_from_ui'
                          )
                    ),
                    center AS (
                        SELECT promoted_genre_id, promoted_title
                        FROM region_tree
                        WHERE region_id = :region_id
                        LIMIT 1
                    ),
                    related_genres AS (
                        SELECT DISTINCT ON (promoted_genre_id)
                            promoted_genre_id AS genre_id,
                            promoted_genre_id AS semantic_root_id,
                            promoted_title AS semantic_root_title,
                            region_depth,
                            0 AS relation_rank
                        FROM region_tree
                        WHERE region_id = :region_id
                           OR promoted_title !~* '\\mmusic\\s+(of|in)\\M'

                        UNION

                        SELECT DISTINCT ON (edge.to_genre_id)
                            edge.to_genre_id AS genre_id,
                            coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)) AS semantic_root_id,
                            coalesce(region_tree.promoted_title, (SELECT promoted_title FROM center)) AS semantic_root_title,
                            region_tree.region_depth + 1 AS region_depth,
                            1 AS relation_rank
                        FROM region_tree
                        JOIN wg_relationship_traversal_edges edge ON edge.from_genre_id = region_tree.promoted_genre_id
                        JOIN wg_genres child ON child.id = edge.to_genre_id
                        WHERE region_tree.region_id <> :region_id
                          AND region_tree.promoted_title ~* '\\mmusic\\s+(of|in)\\M'
                          AND edge.is_ignored = false
                          AND edge.to_genre_id IS NOT NULL
                          AND child.deleted_at IS NULL
                          AND child.is_non_genre = false

                        UNION

                        SELECT DISTINCT ON (rel.genre_id)
                            rel.genre_id,
                            coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)) AS semantic_root_id,
                            coalesce(region_tree.promoted_title, (SELECT promoted_title FROM center)) AS semantic_root_title,
                            region_tree.region_depth + 1 AS region_depth,
                            1 AS relation_rank
                        FROM region_tree
                        JOIN wg_region_genre_relationships rel ON rel.region_id = region_tree.region_id
                        WHERE rel.status = 'accepted'
                          AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')

                        UNION

                        SELECT DISTINCT ON (affinity.genre_id)
                            affinity.genre_id,
                            (SELECT promoted_genre_id FROM center) AS semantic_root_id,
                            (SELECT promoted_title FROM center) AS semantic_root_title,
                            2 AS region_depth,
                            2 AS relation_rank
                        FROM wg_genre_country_affinities affinity
                        WHERE affinity.region_id = :region_id
                          AND affinity.review_status <> 'rejected'
                          AND affinity.score >= 0.55
                          AND affinity.confidence >= 0.50
                    ),
                    best_path AS (
                        SELECT DISTINCT ON (genre_id)
                            genre_id,
                            semantic_root_id,
                            semantic_root_title,
                            region_depth,
                            relation_rank
                        FROM related_genres
                        ORDER BY genre_id, relation_rank, region_depth, semantic_root_title
                    ),
                    playable AS (
                        SELECT genre_id, true AS has_playlist
                        FROM wg_genre_approved_client_playlist_tracks
                        GROUP BY genre_id
                    ),
                    child_counts AS (
                        SELECT e.from_genre_id AS genre_id, COUNT(DISTINCT e.to_genre_id) AS child_connection_count
                        FROM wg_relationship_traversal_edges e
                        JOIN wg_genres child_g ON child_g.id = e.to_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND child_g.deleted_at IS NULL
                          AND child_g.is_non_genre = false
                        GROUP BY e.from_genre_id
                    ),
                    parent_counts AS (
                        SELECT e.to_genre_id AS genre_id, COUNT(DISTINCT e.from_genre_id) AS parent_connection_count
                        FROM wg_relationship_traversal_edges e
                        JOIN wg_genres parent_g ON parent_g.id = e.from_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND parent_g.deleted_at IS NULL
                          AND parent_g.is_non_genre = false
                        GROUP BY e.to_genre_id
                    ),
                    colored_parents AS (
                        SELECT DISTINCT ON (r.genre_id)
                            r.genre_id,
                            COALESCE(parent_c.color_hex, parent_g.infobox_color) AS parent_color
                        FROM wg_music_reachable_parents r
                        JOIN wg_genres parent_g ON parent_g.id = r.parent_genre_id
                        LEFT JOIN wg_genre_colors parent_c ON parent_c.genre_id = r.parent_genre_id
                        WHERE parent_g.deleted_at IS NULL
                          AND parent_g.is_non_genre = false
                          AND COALESCE(parent_c.color_hex, parent_g.infobox_color) IS NOT NULL
                        ORDER BY r.genre_id, r.parent_depth_from_music DESC, parent_g.wikipedia_title
                    )
                    SELECT
                        g.id,
                        g.wikipedia_title,
                        CASE
                            WHEN g.id = (SELECT promoted_genre_id FROM center) THEN 0
                            ELSE greatest(1, best_path.region_depth + 1)
                        END AS depth_from_music,
                        best_path.semantic_root_id,
                        best_path.semantic_root_title,
                        g.monthly_views_p30,
                        COALESCE(c.color_hex, g.infobox_color, colored_parent.parent_color) AS similarity_color,
                        c.confidence AS color_confidence,
                        COALESCE(p.has_playlist, false) AS has_playlist,
                        COALESCE(cc.child_connection_count, 0) AS child_connection_count,
                        COALESCE(pc.parent_connection_count, 0) AS parent_connection_count,
                        (
                            COALESCE(cc.child_connection_count, 0)::float * 1000000000
                            + COALESCE(g.monthly_views_p30, 0)::float
                            + COALESCE(pc.parent_connection_count, 0)::float / 1000000
                        ) AS priority
                    FROM best_path
                    JOIN wg_genres g ON g.id = best_path.genre_id
                    LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                    LEFT JOIN playable p ON p.genre_id = g.id
                    LEFT JOIN child_counts cc ON cc.genre_id = g.id
                    LEFT JOIN parent_counts pc ON pc.genre_id = g.id
                    LEFT JOIN colored_parents colored_parent ON colored_parent.genre_id = g.id
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                      AND (
                          g.id = (SELECT promoted_genre_id FROM center)
                          OR g.wikipedia_title !~* '\\mmusic\\s+(of|in)\\M'
                      )
                    ORDER BY priority DESC, g.wikipedia_title
                """),
                {"region_id": region_id},
            )
        )
        .mappings()
        .fetchall()
    )
    center_genre_id = next(
        (
            row["id"]
            for row in rows
            if int(row["depth_from_music"]) == 0
        ),
        None,
    )
    return [
        row
        for row in rows
        if row["id"] == center_genre_id
        or not MUSIC_REGION_TITLE_RE.search(row["wikipedia_title"] or "")
    ]


@router.get("/cloud", response_model=GenreCloudResult)
async def get_genre_cloud(
    limit: int = Query(
        700,
        ge=25,
        le=5000,
        description="Maximum number of viewport-visible labels to return.",
    ),
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
    atlas: bool = Query(False),
) -> GenreCloudResult:
    """Server-culled label cloud for the current explorer viewport."""
    layout_key = layout_key_for_root(root_genre_id, region_id=region_id)
    async with session_scope() as session:
        if region_id:
            rows = await _region_cloud_rows(session, region_id=region_id)
        else:
            rows = (
                (
                    await session.execute(
                        text("""
                        WITH best_path AS (
                            SELECT DISTINCT ON (r.genre_id)
                                r.genre_id,
                                r.depth_from_music,
                                r.root_genre_id,
                                root_g.wikipedia_title AS root_title
                            FROM wg_music_reachable_parents r
                            JOIN wg_genres root_g ON root_g.id = r.root_genre_id
                            WHERE (
                                CAST(:root_genre_id AS text) IS NULL
                                OR r.genre_id = CAST(:root_genre_id AS text)
                                OR CAST(:root_genre_id AS text) = ANY(r.path_genre_ids)
                            )
                            ORDER BY
                                r.genre_id,
                                r.depth_from_music ASC,
                                root_g.wikipedia_title
                        ),
                        playable AS (
                            SELECT genre_id, true AS has_playlist
                            FROM wg_genre_approved_client_playlist_tracks
                            GROUP BY genre_id
                        ),
                        child_counts AS (
                            SELECT e.from_genre_id AS genre_id, COUNT(DISTINCT e.to_genre_id) AS child_connection_count
                            FROM wg_relationship_traversal_edges e
                            JOIN wg_genres child_g ON child_g.id = e.to_genre_id
                            WHERE e.to_genre_id IS NOT NULL
                              AND child_g.deleted_at IS NULL
                              AND child_g.is_non_genre = false
                            GROUP BY e.from_genre_id
                        ),
                        parent_counts AS (
                            SELECT e.to_genre_id AS genre_id, COUNT(DISTINCT e.from_genre_id) AS parent_connection_count
                            FROM wg_relationship_traversal_edges e
                            JOIN wg_genres parent_g ON parent_g.id = e.from_genre_id
                            WHERE e.to_genre_id IS NOT NULL
                              AND parent_g.deleted_at IS NULL
                              AND parent_g.is_non_genre = false
                            GROUP BY e.to_genre_id
                        ),
                        colored_parents AS (
                            SELECT DISTINCT ON (r.genre_id)
                                r.genre_id,
                                COALESCE(parent_c.color_hex, parent_g.infobox_color) AS parent_color
                            FROM wg_music_reachable_parents r
                            JOIN wg_genres parent_g ON parent_g.id = r.parent_genre_id
                            LEFT JOIN wg_genre_colors parent_c ON parent_c.genre_id = r.parent_genre_id
                            WHERE parent_g.deleted_at IS NULL
                              AND parent_g.is_non_genre = false
                              AND COALESCE(parent_c.color_hex, parent_g.infobox_color) IS NOT NULL
                            ORDER BY r.genre_id, r.parent_depth_from_music DESC, parent_g.wikipedia_title
                        )
                        SELECT
                            g.id,
                            g.wikipedia_title,
                            bp.depth_from_music,
                            bp.root_genre_id AS semantic_root_id,
                            bp.root_title AS semantic_root_title,
                            g.monthly_views_p30,
                            COALESCE(c.color_hex, g.infobox_color, colored_parent.parent_color, root_c.color_hex, root_g.infobox_color) AS similarity_color,
                            c.confidence AS color_confidence,
                            COALESCE(p.has_playlist, false) AS has_playlist,
                            COALESCE(cc.child_connection_count, 0) AS child_connection_count,
                            COALESCE(pc.parent_connection_count, 0) AS parent_connection_count,
                            (
                                COALESCE(cc.child_connection_count, 0)::float * 1000000000
                                + COALESCE(g.monthly_views_p30, 0)::float
                                + COALESCE(pc.parent_connection_count, 0)::float / 1000000
                            ) AS priority
                        FROM best_path bp
                        JOIN wg_genres g ON g.id = bp.genre_id
                        LEFT JOIN wg_genres root_g ON root_g.id = bp.root_genre_id
                        LEFT JOIN wg_genre_colors c ON c.genre_id = g.id
                        LEFT JOIN wg_genre_colors root_c ON root_c.genre_id = bp.root_genre_id
                        LEFT JOIN playable p ON p.genre_id = g.id
                        LEFT JOIN child_counts cc ON cc.genre_id = g.id
                        LEFT JOIN parent_counts pc ON pc.genre_id = g.id
                        LEFT JOIN colored_parents colored_parent ON colored_parent.genre_id = g.id
                        WHERE g.deleted_at IS NULL
                          AND g.is_non_genre = false
                          AND (
                              CAST(:root_genre_id AS text) IS NOT NULL
                              OR g.wikipedia_title !~* '\\mmusic\\s+(of|in)\\M'
                          )
                        ORDER BY priority DESC, g.wikipedia_title
                        """),
                        {"root_genre_id": root_genre_id},
                    )
                )
                .mappings()
                .fetchall()
            )
        display_rows = (
            (
                await session.execute(
                    text("""
                        SELECT
                            genre_id,
                            x,
                            y,
                            text_width,
                            text_height,
                            box_width,
                            box_height,
                            box_pad_x,
                            box_pad_y,
                            priority,
                            lod_score,
                            min_visible_scale,
                            show_scale,
                            hide_scale,
                            lod_rank,
                            lod_tier,
                            display_source
                        FROM wg_genre_cloud_display_nodes
                        WHERE layout_key = :layout_key
                    """),
                    {"layout_key": layout_key},
                )
            )
            .mappings()
            .fetchall()
        )
        layout_rows = [] if display_rows else (
            (
                await session.execute(
                    text("""
                        SELECT
                            genre_id,
                            x,
                            y,
                            width,
                            height,
                            text_width,
                            text_height,
                            box_width,
                            box_height,
                            box_pad_x,
                            box_pad_y,
                            priority,
                            lod_score,
                            radial_x,
                            radial_y,
                            radial_compaction_version,
                            min_visible_scale,
                            show_scale,
                            hide_scale,
                            lod_rank,
                            lod_tier
                        FROM wg_genre_semantic_layouts
                        WHERE layout_key = :layout_key
                    """),
                    {"layout_key": layout_key},
                )
            )
            .mappings()
            .fetchall()
        )
        semantic_edges = []
        if selected_genre_id and selected_genre_id != _CLOUD_ROOT_ID:
            semantic_edges = (
                (
                    await session.execute(
                        text("""
                            SELECT from_genre_id, to_genre_id, weight
                            FROM wg_genre_semantic_edges
                            WHERE layout_key = :layout_key
                        """),
                        {"layout_key": layout_key},
                    )
                )
                .mappings()
                .fetchall()
            )

    row_dicts = [dict(row) for row in rows]
    display_dicts = [dict(row) for row in display_rows]
    layout_dicts = [dict(row) for row in layout_rows]
    distance_map = _cloud_selected_distance_map(
        (dict(row) for row in semantic_edges),
        selected_genre_id=selected_genre_id,
    )
    center_id = root_genre_id or _CLOUD_ROOT_ID
    if region_id:
        center_row = min(
            row_dicts,
            key=lambda row: (
                int(row["depth_from_music"])
                if row.get("depth_from_music") is not None
                else 999,
                str(row.get("wikipedia_title") or "").lower(),
            ),
            default=None,
        )
        center_id = center_row.get("id") if center_row else _CLOUD_ROOT_ID
    root_row = next((row for row in row_dicts if row.get("id") == center_id), None)
    laid_out = _layout_cloud_nodes(
        row_dicts,
        center_id=center_id,
        center_title=root_row.get("wikipedia_title") if root_row else "Music",
    )
    materialized_applied = 0
    radial_applied = 0
    layout_source = "fallback_radial"
    if display_dicts:
        real_node_count = max(1, len([node for node in laid_out if node["id"] != _CLOUD_ROOT_ID]))
        laid_out, materialized_applied, radial_applied = _apply_cloud_display_cache(
            laid_out,
            display_dicts,
        )
        if materialized_applied / real_node_count >= 0.8:
            layout_source = "cloud_display_cache"
        else:
            laid_out = _layout_cloud_nodes(
                row_dicts,
                center_id=center_id,
                center_title=root_row.get("wikipedia_title") if root_row else "Music",
            )
            materialized_applied = 0
            radial_applied = 0
    elif layout_dicts:
        real_node_count = max(1, len([node for node in laid_out if node["id"] != _CLOUD_ROOT_ID]))
        laid_out, materialized_applied, radial_applied = _apply_materialized_cloud_layout(
            laid_out,
            layout_dicts,
        )
        if materialized_applied / real_node_count >= 0.8:
            layout_source = (
                "radial_compacted"
                if radial_applied / real_node_count >= 0.8
                else "semantic_materialized"
            )
        else:
            laid_out = _layout_cloud_nodes(
                row_dicts,
                center_id=center_id,
                center_title=root_row.get("wikipedia_title") if root_row else "Music",
            )
            materialized_applied = 0
            radial_applied = 0
    laid_out = _apply_cloud_selected_distances(laid_out, distance_map)
    bounds = _cloud_bounds(laid_out)
    radial_layout = layout_source in {"radial_compacted", "cloud_display_cache"}
    if atlas:
        visible_nodes = _viewport_cloud_nodes(
            laid_out,
            x_min=None,
            x_max=None,
            y_min=None,
            y_max=None,
            scale=scale,
            selected_genre_id=selected_genre_id or root_genre_id or center_id,
            limit=limit,
        )
    else:
        visible_nodes = _cull_cloud_nodes(
            laid_out,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            scale=scale,
            view_tx=view_tx,
            view_ty=view_ty,
            selected_genre_id=selected_genre_id or root_genre_id or center_id,
            limit=None if radial_layout and not atlas else limit,
        )
    nodes = [
        GenreCloudNodeOut(
            **node,
        )
        for node in visible_nodes
    ]
    return GenreCloudResult(
        nodes=nodes,
        stats={
            "nodes": len(nodes),
            "total_nodes": len(laid_out),
            "bounds": bounds,
            "layout_key": layout_key,
            "layout_source": layout_source,
            "region_id": region_id,
            "center_genre_id": center_id if center_id != _CLOUD_ROOT_ID else None,
            "display_cache_nodes": len(display_dicts),
            "materialized_nodes": materialized_applied,
            "radial_nodes": radial_applied,
            "selected_genre_id": selected_genre_id,
            "selected_distance_nodes": len(distance_map),
            "lod": {
                "scale": scale,
                "score_version": "stable-lod-v1",
                "atlas": atlas,
                "radial_layout": radial_layout,
            },
        },
    )


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}                                                 #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}", response_model=GenreDetail)
async def get_genre(genre_id: str) -> GenreDetail:
    """Full genre detail: edges (in + out), aliases, origins, instruments."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")
        return await _build_genre_detail(session, row)


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/playlist                                       #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/playlist", response_model=GenrePlaylistResult)
async def get_genre_playlist(genre_id: str) -> GenrePlaylistResult:
    """Manually curated YouTube playlist entries for a genre."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        tracks = (
            await session.execute(
                text(f"""
                    SELECT tracks.genre_id, tracks.ordinal, tracks.song_title, tracks.artist, tracks.youtube_url
                    FROM wg_genre_approved_client_playlist_tracks tracks
                    WHERE tracks.genre_id = :genre_id
                    ORDER BY
                        tracks.ordinal,
                        tracks.artist,
                        tracks.song_title
                """),
                {"genre_id": genre_id},
            )
        ).mappings()

        return GenrePlaylistResult(
            genre_id=row["id"],
            wikipedia_title=row["wikipedia_title"],
            tracks=[GenrePlaylistTrackOut(**dict(track)) for track in tracks],
        )


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/regional-variants                              #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/regional-variants", response_model=RegionVariantsResult)
async def get_regional_variants(genre_id: str) -> RegionVariantsResult:
    """Return plain country/regional pages that match a genre title."""
    async with session_scope() as session:
        if genre_id == MUSIC_ROOT_ID:
            return await _regional_variants_for_title(
                session,
                genre_id=None,
                title="Music",
                root_mode=True,
            )

        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")
        return await _regional_variants_for_title(
            session,
            genre_id=row["id"],
            title=row["wikipedia_title"],
        )


async def _promoted_region_for_genre(session, genre_id: str):
    return (
        (
            await session.execute(
                text("""
            SELECT region.id AS region_id,
                   region.canonical_name,
                   region.kind AS region_kind,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM wg_region_promoted_genres promoted
            JOIN wg_regions region ON region.id = promoted.region_id
            JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = genre.id
            WHERE promoted.genre_id = :genre_id
            LIMIT 1
        """),
                {"genre_id": genre_id},
            )
        )
        .mappings()
        .fetchone()
    )


async def _root_country_map_items(session) -> list[MapRegionItemOut]:
    rows = (
        (
            await session.execute(
                text("""
            SELECT region.id AS region_id,
                   region.canonical_name,
                   region.kind AS region_kind,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM wg_regions region
            JOIN wg_region_promoted_genres promoted ON promoted.region_id = region.id
            JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = genre.id
            WHERE region.kind = 'country'
              AND coalesce(region.raw_payload #>> '{region_accessibility,manual_access}', 'false') = 'true'
              AND genre.deleted_at IS NULL
              AND genre.is_non_genre = false
            ORDER BY region.canonical_name
        """),
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        _map_item_from_region_row(
            row, map_key=WORLD_MAP_KEY, match_type="music_region", role="country"
        )
        for row in rows
    ]


async def _region_child_map_items(
    session,
    *,
    parent_region_id: str,
    map_key: str,
) -> list[MapRegionItemOut]:
    rows = (
        (
            await session.execute(
                text("""
            SELECT DISTINCT ON (child.id)
                   child.id AS region_id,
                   child.canonical_name,
                   child.kind AS region_kind,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence,
                   child.raw_payload #>> '{region_accessibility,ui_visibility}' AS ui_visibility
            FROM wg_region_relationships rel
            JOIN wg_regions child ON child.id = rel.from_region_id
            JOIN wg_region_promoted_genres promoted ON promoted.region_id = child.id
            JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = genre.id
            WHERE rel.to_region_id = :parent_region_id
              AND rel.status = 'accepted'
              AND genre.deleted_at IS NULL
              AND genre.is_non_genre = false
              AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
              )
              AND (
                (:map_key = :us_map_key AND (
                  child.kind IN ('subregion', 'territory')
                  OR child.raw_payload #>> '{region_accessibility,ui_visibility}' = 'special_country_subregion'
                ))
                OR (:map_key <> :us_map_key AND child.kind = 'country')
              )
            ORDER BY child.id,
                     CASE
                       WHEN child.raw_payload #>> '{region_accessibility,ui_visibility}' = 'special_country_subregion' THEN 0
                       WHEN child.kind IN ('subregion', 'territory') THEN 1
                       ELSE 2
                     END,
                     rel.confidence DESC
        """),
                {
                    "parent_region_id": parent_region_id,
                    "map_key": map_key,
                    "us_map_key": US_MAP_KEY,
                },
            )
        )
        .mappings()
        .fetchall()
    )
    role = "subregion" if map_key == US_MAP_KEY else "country"
    items = [
        _map_item_from_region_row(row, map_key=map_key, match_type="music_region", role=role)
        for row in rows
    ]
    if map_key == US_MAP_KEY:
        items = [item for item in items if item.feature_key in US_FEATURE_NAMES]
    return items


async def _region_parent_map_items(
    session, *, region_id: str, map_key: str
) -> list[MapRegionItemOut]:
    rows = (
        (
            await session.execute(
                text("""
            SELECT DISTINCT ON (parent.id)
                   parent.id AS region_id,
                   parent.canonical_name,
                   parent.kind AS region_kind,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM wg_region_relationships rel
            JOIN wg_regions parent ON parent.id = rel.to_region_id
            JOIN wg_region_promoted_genres promoted ON promoted.region_id = parent.id
            JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = genre.id
            WHERE rel.from_region_id = :region_id
              AND rel.status = 'accepted'
              AND parent.kind NOT IN ('continent')
              AND genre.deleted_at IS NULL
              AND genre.is_non_genre = false
            ORDER BY parent.id, rel.confidence DESC
        """),
                {"region_id": region_id},
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        _map_item_from_region_row(
            row, map_key=map_key, match_type="parent_region", role="parent_region"
        )
        for row in rows
    ]


async def _selected_region_context_highlights(
    session,
    *,
    genre_id: str,
    map_key: str,
) -> list[MapRegionItemOut]:
    rows = (
        (
            await session.execute(
                text("""
            WITH origin_regions AS (
                SELECT DISTINCT region.id AS region_id
                FROM wg_origins origin
                JOIN wg_regions region
                  ON lower(region.canonical_name) = lower(origin.parsed_region)
                WHERE origin.genre_id = :genre_id
                  AND origin.parsed_region IS NOT NULL
            ),
            relationship_regions AS (
                SELECT DISTINCT rel.region_id
                FROM wg_region_genre_relationships rel
                WHERE rel.genre_id = :genre_id
                  AND rel.status = 'accepted'
                  AND rel.relation not in ('regional_style_mention', 'influence_or_context')
            ),
            selected AS (
                SELECT region_id FROM origin_regions
                UNION
                SELECT region_id FROM relationship_regions
            )
            SELECT region.id AS region_id,
                   region.canonical_name,
                   region.kind AS region_kind,
                   promoted.genre_id,
                   promoted.wikipedia_title,
                   genre.monthly_views_p30,
                   c.color_hex AS similarity_color,
                   c.confidence AS color_confidence
            FROM selected
            JOIN wg_regions region ON region.id = selected.region_id
            LEFT JOIN wg_region_promoted_genres promoted ON promoted.region_id = region.id
            LEFT JOIN wg_genres genre ON genre.id = promoted.genre_id
            LEFT JOIN wg_genre_colors c ON c.genre_id = genre.id
            WHERE coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                'collapsed',
                'rejected',
                'demoted_source',
                'hidden_from_ui'
            )
        """),
                {"genre_id": genre_id},
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        _map_item_from_region_row(row, map_key=map_key, match_type="region_context", role="context")
        for row in rows
    ]


async def _us_context_for_region(session, selected_region) -> tuple[str, list[MapRegionItemOut]]:
    active_map = _region_map_key(selected_region["region_id"])
    if active_map == US_MAP_KEY:
        return US_MAP_KEY, await _region_child_map_items(
            session,
            parent_region_id="region-united-states",
            map_key=US_MAP_KEY,
        )
    return WORLD_MAP_KEY, []


@router.get("/{genre_id}/map-context", response_model=MapContextOut)
async def get_map_context(genre_id: str) -> MapContextOut:
    """Return map domain, selectable regions, and context highlights for graph mode."""
    async with session_scope() as session:
        if genre_id == MUSIC_ROOT_ID:
            selectable_regions = await _annotate_map_items_for_list(
                session,
                await _root_country_map_items(session),
                map_key=WORLD_MAP_KEY,
            )
            selectable_regions = await _annotate_root_map_items_for_list(
                session, selectable_regions
            )
            return MapContextOut(
                genre_id=None,
                wikipedia_title="Music",
                active_map=WORLD_MAP_KEY,
                map_label=None,
                selectable_regions=selectable_regions,
                context_highlights=[],
                parent_regions=[],
            )

        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        selected_region = await _promoted_region_for_genre(session, genre_id)
        if selected_region:
            active_map, selectable_regions = await _us_context_for_region(session, selected_region)
            if not selectable_regions and selected_region["region_kind"] not in (
                "country",
                "territory",
            ):
                selectable_regions = await _region_child_map_items(
                    session,
                    parent_region_id=selected_region["region_id"],
                    map_key=WORLD_MAP_KEY,
                )
            selected_item = _map_item_from_region_row(
                selected_region,
                map_key=active_map,
                match_type="selected_region",
                role=selected_region["region_kind"] or "region",
            )
            selectable_regions = await _expand_map_items_with_pure_region_graph(
                session,
                [selected_item, *selectable_regions],
                map_key=active_map,
            )
            selectable_regions = [
                item
                for item in selectable_regions
                if item.region_id != selected_item.region_id or item.match_type != "selected_region"
            ]
            selectable_regions = await _group_country_map_items_with_regional_children(
                session,
                parent_genre_id=row["id"],
                parent_title=row["wikipedia_title"],
                items=selectable_regions,
            )
            selectable_regions = await _annotate_map_items_for_list(
                session,
                selectable_regions,
                map_key=active_map,
            )
            context_highlights = [selected_item]
            return MapContextOut(
                genre_id=row["id"],
                wikipedia_title=row["wikipedia_title"],
                active_map=active_map,
                map_label=selected_item.region_name,
                selected_region=selected_item,
                selectable_regions=selectable_regions,
                context_highlights=context_highlights,
                parent_regions=await _region_parent_map_items(
                    session,
                    region_id=selected_region["region_id"],
                    map_key=active_map,
                ),
            )

        variants = await _regional_variants_for_title(
            session,
            genre_id=row["id"],
            title=row["wikipedia_title"],
        )
        selectable_regions = [
            _map_item_from_variant(item, map_key=WORLD_MAP_KEY) for item in variants.items
        ]
        pure_region_matches = await _pure_region_matches_for_genre(
            session,
            genre_id=row["id"],
            map_key=WORLD_MAP_KEY,
        )
        selectable_regions = await _expand_map_items_with_pure_region_graph(
            session,
            [*selectable_regions, *pure_region_matches],
            map_key=WORLD_MAP_KEY,
        )
        selectable_regions = await _group_country_map_items_with_regional_children(
            session,
            parent_genre_id=row["id"],
            parent_title=row["wikipedia_title"],
            items=selectable_regions,
        )
        selectable_regions = await _annotate_map_items_for_list(
            session,
            selectable_regions,
            map_key=WORLD_MAP_KEY,
        )
        return MapContextOut(
            genre_id=row["id"],
            wikipedia_title=row["wikipedia_title"],
            active_map=WORLD_MAP_KEY,
            map_label=_label_for_region_match(row["wikipedia_title"])
            if selectable_regions
            else None,
            selectable_regions=selectable_regions,
            context_highlights=[],
            parent_regions=[],
        )


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/edges                                           #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/edges", response_model=list[EdgeOut])
async def get_genre_edges(
    genre_id: str,
    relation: str | None = Query(None, description="Filter by relation type."),
    direction: str = Query("out", pattern="^(out|in|both)$"),
    projection: str = Query(
        "detail",
        pattern="^(detail|traversal|neighbor)$",
        description="Relationship projection: stored detail, parent-to-child traversal, or undirected neighbor expansion.",
    ),
) -> list[EdgeOut]:
    """Filtered edge list for a genre."""
    edge_view = {
        "detail": "wg_relationship_detail_edges",
        "traversal": "wg_relationship_traversal_edges",
        "neighbor": "wg_relationship_neighbor_edges",
    }[projection]

    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rel_filter = (
            """
            AND (
                e.relation = :relation
                OR (
                    :relation = ANY(:display_relations)
                    AND e.relation = :related_relation
                    AND e.evidence_relation = :relation
                )
            )
        """
            if relation
            else ""
        )
        params: dict[str, object] = {"gid": genre_id, "layout_key": layout_key_for_root(None)}
        if relation:
            params["relation"] = relation
            params["display_relations"] = list(DISPLAY_RELATIONS)
            params["related_relation"] = RELATED_RELATION

        results: list[EdgeOut] = []

        if direction in ("out", "both"):
            rows = (
                (
                    await session.execute(
                        text(f"""
                    SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                           e.relation, e.source, e.ordinal, e.evidence_relation,
                           to_g.monthly_views_p30 AS to_monthly_views_p30,
                           to_c.color_hex AS to_similarity_color,
                           to_c.confidence AS to_color_confidence,
                           to_layout.text_width AS to_text_width,
                           to_layout.text_height AS to_text_height,
                           to_layout.box_width AS to_box_width,
                           to_layout.box_height AS to_box_height,
                           to_layout.box_pad_x AS to_box_pad_x,
                           to_layout.box_pad_y AS to_box_pad_y
                    FROM {edge_view} e
                    LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                    LEFT JOIN wg_genre_colors to_c ON to_c.genre_id = e.to_genre_id
                    LEFT JOIN wg_genre_semantic_layouts to_layout
                      ON to_layout.genre_id = e.to_genre_id
                     AND to_layout.layout_key = :layout_key
                    WHERE e.from_genre_id = :gid {rel_filter}
                      AND e.is_ignored = false
                      AND (
                        e.to_genre_id IS NULL
                        OR (to_g.deleted_at IS NULL AND to_g.is_non_genre = false)
                      )
                    ORDER BY relation, source, ordinal
                """),
                        params,
                    )
                )
                .mappings()
                .fetchall()
            )
            results.extend(EdgeOut(**dict(r)) for r in rows)

        if direction in ("in", "both"):
            rows = (
                (
                    await session.execute(
                        text(f"""
                    SELECT e.from_genre_id, e.to_genre_id, e.to_raw_label,
                           e.relation, e.source, e.ordinal, e.evidence_relation,
                           to_g.monthly_views_p30 AS to_monthly_views_p30,
                           to_c.color_hex AS to_similarity_color,
                           to_c.confidence AS to_color_confidence,
                           to_layout.text_width AS to_text_width,
                           to_layout.text_height AS to_text_height,
                           to_layout.box_width AS to_box_width,
                           to_layout.box_height AS to_box_height,
                           to_layout.box_pad_x AS to_box_pad_x,
                           to_layout.box_pad_y AS to_box_pad_y
                    FROM {edge_view} e
                    JOIN wg_genres g ON g.id = e.from_genre_id
                    LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                    LEFT JOIN wg_genre_colors to_c ON to_c.genre_id = e.to_genre_id
                    LEFT JOIN wg_genre_semantic_layouts to_layout
                      ON to_layout.genre_id = e.to_genre_id
                     AND to_layout.layout_key = :layout_key
                    WHERE e.to_genre_id = :gid {rel_filter}
                      AND e.is_ignored = false
                      AND g.deleted_at IS NULL
                      AND g.is_non_genre = false
                    ORDER BY relation, source, ordinal
                """),
                        params,
                    )
                )
                .mappings()
                .fetchall()
            )
            results.extend(EdgeOut(**dict(r)) for r in rows)

        return results


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/reachable-parents                               #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/reachable-parents", response_model=list[ReachableParentOut])
async def get_genre_reachable_parents(
    genre_id: str,
    relation: list[str] | None = Query(
        None,
        description="Optional parent relation filter. Repeat for multiple values.",
    ),
) -> list[ReachableParentOut]:
    """Return display parents that can be revealed from the synthetic Music root."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        params: dict = {
            "gid": genre_id,
            "relations": relation or [],
            "has_relation_filter": bool(relation),
            "related_relation": RELATED_RELATION,
        }

        rows = (
            (
                await session.execute(
                    text("""
                SELECT
                    r.genre_id,
                    genre_g.monthly_views_p30 AS genre_monthly_views_p30,
                    genre_origin.year_start AS genre_year_start,
                    r.parent_genre_id,
                    COALESCE(parent_g.wikipedia_title, 'Music') AS parent_title,
                    parent_g.monthly_views_p30 AS parent_monthly_views_p30,
                    parent_origin.year_start AS parent_year_start,
                    r.root_genre_id,
                    root_g.wikipedia_title AS root_title,
                    root_g.monthly_views_p30 AS root_monthly_views_p30,
                    r.parent_relation,
                    parent_edge.relation AS parent_stored_relation,
                    parent_edge.evidence_relation AS parent_evidence_relation,
                    r.parent_source,
                    r.parent_ordinal,
                    r.parent_depth_from_music,
                    r.depth_from_music,
                    r.path_genre_ids,
                    (
                        SELECT array_agg(path_g.wikipedia_title ORDER BY path_item.ordinality)
                        FROM unnest(r.path_genre_ids)
                            WITH ORDINALITY AS path_item(genre_id, ordinality)
                        JOIN wg_genres path_g ON path_g.id = path_item.genre_id
                    ) AS path_titles
                FROM wg_music_reachable_parents r
                JOIN wg_genres genre_g ON genre_g.id = r.genre_id
                JOIN wg_genres root_g ON root_g.id = r.root_genre_id
                LEFT JOIN wg_genres parent_g ON parent_g.id = r.parent_genre_id
                LEFT JOIN (
                    SELECT genre_id, min(parsed_year_start) AS year_start
                    FROM wg_origins
                    WHERE kind = 'temporal'
                      AND parsed_year_start IS NOT NULL
                    GROUP BY genre_id
                ) genre_origin ON genre_origin.genre_id = r.genre_id
                LEFT JOIN (
                    SELECT genre_id, min(parsed_year_start) AS year_start
                    FROM wg_origins
                    WHERE kind = 'temporal'
                      AND parsed_year_start IS NOT NULL
                    GROUP BY genre_id
                ) parent_origin ON parent_origin.genre_id = r.parent_genre_id
                LEFT JOIN wg_relationship_traversal_edges parent_edge
                    ON parent_edge.from_genre_id = r.parent_genre_id
                   AND parent_edge.to_genre_id = r.genre_id
                   AND parent_edge.source = r.parent_source
                   AND parent_edge.ordinal = r.parent_ordinal
                   AND (
                    parent_edge.relation = r.parent_relation
                    OR (
                      parent_edge.relation = :related_relation
                      AND parent_edge.evidence_relation = r.parent_relation
                    )
                   )
                WHERE r.genre_id = :gid
                  AND (
                    :has_relation_filter = false
                    OR r.parent_relation = ANY(:relations)
                  )
                ORDER BY
                    r.parent_depth_from_music,
                    parent_title,
                    r.parent_relation,
                    r.parent_source,
                    r.parent_ordinal
            """),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

    return [ReachableParentOut(**dict(r)) for r in rows]


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/neighbors                                       #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/neighbors", response_model=list[NeighborOut])
async def get_genre_neighbors(
    genre_id: str,
    depth: int = Query(1, ge=1, le=3, description="BFS depth (max 3)."),
    relation: str | None = Query(None, description="Restrict to one relation type."),
) -> list[NeighborOut]:
    """BFS expansion up to *depth* hops. Useful for graph visualisations."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rel_filter = (
            """
            AND (
                e.relation = :relation
                OR (
                    :relation = ANY(:display_relations)
                    AND e.relation = :related_relation
                    AND e.evidence_relation = :relation
                )
            )
        """
            if relation
            else ""
        )
        params: dict = {
            "start": genre_id,
            "max_depth": depth - 1,
            "display_relations": list(DISPLAY_RELATIONS),
            "related_relation": RELATED_RELATION,
        }
        if relation:
            params["relation"] = relation

        # Recursive CTE with cycle guard via `visited` array.
        rows = (
            (
                await session.execute(
                    text(f"""
                WITH RECURSIVE bfs AS (
                    SELECT
                        e.to_genre_id       AS genre_id,
                        CASE
                          WHEN e.relation = :related_relation
                           AND e.evidence_relation = ANY(:display_relations)
                          THEN e.evidence_relation
                          ELSE e.relation
                        END AS relation,
                        e.source,
                        0                   AS depth,
                        ARRAY[e.from_genre_id, e.to_genre_id] AS visited
                    FROM wg_relationship_neighbor_edges e
                    WHERE e.from_genre_id = :start
                      AND e.to_genre_id IS NOT NULL
                      AND e.is_ignored = false
                      {rel_filter}

                    UNION ALL

                    SELECT
                        e.to_genre_id,
                        CASE
                          WHEN e.relation = :related_relation
                           AND e.evidence_relation = ANY(:display_relations)
                          THEN e.evidence_relation
                          ELSE e.relation
                        END AS relation,
                        e.source,
                        bfs.depth + 1,
                        bfs.visited || e.to_genre_id
                    FROM wg_relationship_neighbor_edges e
                    JOIN bfs ON bfs.genre_id = e.from_genre_id
                    WHERE e.to_genre_id IS NOT NULL
                      AND e.is_ignored = false
                      AND NOT (e.to_genre_id = ANY(bfs.visited))
                      AND bfs.depth < :max_depth
                      {rel_filter}
                )
                SELECT DISTINCT ON (bfs.genre_id)
                    g.id, g.wikipedia_title, g.wikidata_qid,
                    g.has_infobox, g.infobox_color,
                    bfs.relation, bfs.source,
                    bfs.depth
                FROM bfs
                JOIN wg_genres g ON g.id = bfs.genre_id
                WHERE g.deleted_at IS NULL
                  AND g.is_non_genre = false
                ORDER BY bfs.genre_id, bfs.depth
            """),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

    return [
        NeighborOut(
            id=r["id"],
            wikipedia_title=r["wikipedia_title"],
            wikidata_qid=r["wikidata_qid"],
            has_infobox=r["has_infobox"],
            infobox_color=r["infobox_color"],
            relation=r["relation"],
            source=r["source"],
            depth=r["depth"] + 1,  # 1-indexed for callers
        )
        for r in rows
    ]


# ------------------------------------------------------------------ #
# GET /v1/genres/{id}/pageviews                                       #
# ------------------------------------------------------------------ #


@router.get("/{genre_id}/pageviews", response_model=list[PageviewEntry])
async def get_genre_pageviews(genre_id: str) -> list[PageviewEntry]:
    """Monthly pageview history for a genre (most recent first)."""
    async with session_scope() as session:
        row = await _get_genre_row(session, genre_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Genre '{genre_id}' not found.")

        rows = (
            (
                await session.execute(
                    text("""
                SELECT year, month, views
                FROM wg_pageviews
                WHERE genre_id = :gid
                ORDER BY year DESC, month DESC
            """),
                    {"gid": genre_id},
                )
            )
            .mappings()
            .fetchall()
        )

    return [PageviewEntry(**dict(r)) for r in rows]
