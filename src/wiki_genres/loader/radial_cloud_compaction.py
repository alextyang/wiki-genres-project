"""Radial constrained rectangle compaction for semantic cloud layouts.

This module does not create a new semantic layout. It reads the known-good
materialized ``x/y`` cloud coordinates, treats them as anchors, and writes a
second coordinate set that is packed inward from the Music center.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.semantic_cloud_layout import GENERAL_LAYOUT_KEY, layout_key_for_root

logger = structlog.get_logger(__name__)

COMPACTION_VERSION = "radial-constrained-rect-v1"
CENTER_LABEL_WIDTH = 37.7
CENTER_LABEL_HEIGHT = 16.25
LABEL_PAD_X = 5.0
LABEL_PAD_Y = 4.0


@dataclass
class CompactNode:
    genre_id: str
    title: str
    x: float
    y: float
    width: float
    height: float
    box_width: float
    box_height: float
    box_pad_x: float
    box_pad_y: float
    lod_rank: int
    lod_score: float
    priority: float
    metadata: dict[str, Any] = field(default_factory=dict)
    radial_x: float = 0.0
    radial_y: float = 0.0
    radial_radius: float = 0.0
    angle_delta: float = 0.0

    @property
    def radius(self) -> float:
        return math.hypot(self.x, self.y)

    @property
    def angle(self) -> float:
        return math.atan2(self.y, self.x) if self.x or self.y else 0.0


@dataclass
class RadialCompactionStats:
    layout_key: str
    total_nodes: int = 0
    updated_nodes: int = 0
    dry_run: bool = False
    metrics: dict[str, float | int] = field(default_factory=dict)
    sample: list[dict[str, Any]] = field(default_factory=list)


def _angle_delta(left: float, right: float) -> float:
    return math.atan2(math.sin(left - right), math.cos(left - right))


def _rect_for(
    x: float,
    y: float,
    box_width: float,
    box_height: float,
) -> tuple[float, float, float, float]:
    half_width = box_width / 2
    half_height = box_height / 2
    return (x - half_width, x + half_width, y - half_height, y + half_height)


def _rects_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return (
        left[0] < right[1]
        and left[1] > right[0]
        and left[2] < right[3]
        and left[3] > right[2]
    )


class SpatialIndex:
    def __init__(self, *, cell_size: float = 96.0) -> None:
        self.cell_size = cell_size
        self.cells: dict[tuple[int, int], list[tuple[str, tuple[float, float, float, float]]]] = (
            defaultdict(list)
        )

    def _keys(self, rect: tuple[float, float, float, float]) -> tuple[range, range]:
        min_x, max_x, min_y, max_y = rect
        x_keys = range(
            math.floor(min_x / self.cell_size),
            math.floor(max_x / self.cell_size) + 1,
        )
        y_keys = range(
            math.floor(min_y / self.cell_size),
            math.floor(max_y / self.cell_size) + 1,
        )
        return x_keys, y_keys

    def collides(self, rect: tuple[float, float, float, float]) -> bool:
        x_keys, y_keys = self._keys(rect)
        for key_x in x_keys:
            for key_y in y_keys:
                if any(
                    _rects_overlap(rect, other)
                    for _, other in self.cells.get((key_x, key_y), ())
                ):
                    return True
        return False

    def add(self, node_id: str, rect: tuple[float, float, float, float]) -> None:
        x_keys, y_keys = self._keys(rect)
        for key_x in x_keys:
            for key_y in y_keys:
                self.cells[(key_x, key_y)].append((node_id, rect))


def _spatial_index_without(nodes: list[CompactNode], skipped_genre_id: str) -> SpatialIndex:
    spatial = SpatialIndex()
    spatial.add(
        "__music_root__",
        _rect_for(
            0.0,
            0.0,
            CENTER_LABEL_WIDTH + LABEL_PAD_X * 2,
            CENTER_LABEL_HEIGHT + LABEL_PAD_Y * 2,
        ),
    )
    for node in nodes:
        if node.genre_id == skipped_genre_id:
            continue
        spatial.add(
            node.genre_id,
            _rect_for(node.radial_x, node.radial_y, node.box_width, node.box_height),
        )
    return spatial


def _repair_remaining_overlaps(
    nodes: list[CompactNode],
    *,
    angle_offsets: list[float],
    radius_step: float,
    max_outward_extra: float = 420.0,
    passes: int = 6,
) -> int:
    repaired = 0
    for _ in range(passes):
        moved = False
        for node in sorted(nodes, key=lambda item: (-item.lod_rank, item.title.lower())):
            spatial = _spatial_index_without(nodes, node.genre_id)
            current_rect = _rect_for(node.radial_x, node.radial_y, node.box_width, node.box_height)
            if not spatial.collides(current_rect):
                continue

            original_angle = node.angle
            current_radius = math.hypot(node.radial_x, node.radial_y)
            max_radius = max(node.radius, current_radius) + max_outward_extra
            best: tuple[float, float, float] | None = None
            best_cost = float("inf")
            radius = current_radius + radius_step
            while radius <= max_radius:
                for offset in angle_offsets:
                    candidate_angle = original_angle + offset
                    x = math.cos(candidate_angle) * radius
                    y = math.sin(candidate_angle) * radius
                    rect = _rect_for(x, y, node.box_width, node.box_height)
                    if spatial.collides(rect):
                        continue
                    delta = abs(_angle_delta(candidate_angle, original_angle))
                    beyond_anchor = max(0.0, radius - node.radius)
                    cost = radius + delta * 420.0 + beyond_anchor * 12.0
                    if cost < best_cost:
                        best = (x, y, candidate_angle)
                        best_cost = cost
                if best is not None:
                    break
                radius += radius_step

            if best is None:
                continue

            node.radial_x, node.radial_y, packed_angle = best
            node.radial_radius = math.hypot(node.radial_x, node.radial_y)
            node.angle_delta = abs(_angle_delta(packed_angle, original_angle))
            repaired += 1
            moved = True
        if not moved:
            break

    return repaired


def _bounds(nodes: list[CompactNode], *, radial: bool = False) -> dict[str, float]:
    if not nodes:
        return {"min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0}
    return {
        "min_x": min((node.radial_x if radial else node.x) - node.box_width / 2 for node in nodes),
        "max_x": max((node.radial_x if radial else node.x) + node.box_width / 2 for node in nodes),
        "min_y": min((node.radial_y if radial else node.y) - node.box_height / 2 for node in nodes),
        "max_y": max((node.radial_y if radial else node.y) + node.box_height / 2 for node in nodes),
    }


def _bounds_area(bounds: dict[str, float]) -> float:
    return max(1.0, bounds["max_x"] - bounds["min_x"]) * max(1.0, bounds["max_y"] - bounds["min_y"])


def _candidate_angle_offsets(lane_width: float, *, steps: int = 4) -> list[float]:
    offsets = [0.0]
    step = lane_width * 0.85
    for index in range(1, steps + 1):
        offsets.extend((index * step, -index * step))
    return offsets


def compact_nodes_radially(
    nodes: list[CompactNode],
    *,
    lanes: int = 96,
    radius_step: float = 8.0,
    angular_steps: int = 8,
    inner_radius: float = 0.0,
    max_outward_extra: float = 720.0,
) -> RadialCompactionStats:
    """Pack nodes from the center outward while preserving semantic angle."""
    stats = RadialCompactionStats(layout_key=GENERAL_LAYOUT_KEY, total_nodes=len(nodes))
    if not nodes:
        return stats

    lane_width = math.tau / max(8, lanes)
    angle_offsets = _candidate_angle_offsets(lane_width, steps=angular_steps)
    max_seen_radius = max(node.radius for node in nodes)
    spatial = SpatialIndex()
    spatial.add(
        "__music_root__",
        _rect_for(
            0.0,
            0.0,
            CENTER_LABEL_WIDTH + LABEL_PAD_X * 2,
            CENTER_LABEL_HEIGHT + LABEL_PAD_Y * 2,
        ),
    )
    ordered = sorted(
        nodes,
        key=lambda node: (
            node.radius,
            node.angle,
            node.metadata.get("root_title") or "",
            node.title.lower(),
        ),
    )
    outward_count = 0

    for node in ordered:
        original_angle = node.angle
        original_radius = node.radius
        max_radius = max(original_radius, inner_radius) + max_outward_extra
        best: tuple[float, float, float] | None = None
        radius = max(0.0, inner_radius)
        while radius <= max_radius:
            ring_best: tuple[float, float, float] | None = None
            ring_cost = float("inf")
            for offset in angle_offsets:
                candidate_angle = original_angle + offset
                x = math.cos(candidate_angle) * radius
                y = math.sin(candidate_angle) * radius
                rect = _rect_for(x, y, node.box_width, node.box_height)
                if spatial.collides(rect):
                    continue
                delta = abs(_angle_delta(candidate_angle, original_angle))
                beyond_anchor = max(0.0, radius - original_radius)
                displacement = math.hypot(x - node.x, y - node.y)
                cost = delta * 360.0 + beyond_anchor * 12.0 + displacement * 0.01
                if cost < ring_cost:
                    ring_best = (x, y, candidate_angle)
                    ring_cost = cost
            if ring_best is not None:
                best = ring_best
                break
            radius += radius_step

        if best is None:
            best = (node.x, node.y, original_angle)
            outward_count += 1

        node.radial_x, node.radial_y, packed_angle = best
        node.radial_radius = math.hypot(node.radial_x, node.radial_y)
        node.angle_delta = abs(_angle_delta(packed_angle, original_angle))
        if node.radial_radius > node.radius + 1.0:
            outward_count += 1
        spatial.add(node.genre_id, _rect_for(node.radial_x, node.radial_y, node.box_width, node.box_height))

    original_bounds = _bounds(nodes)
    radial_bounds = _bounds(nodes, radial=True)
    original_area = _bounds_area(original_bounds)
    radial_area = _bounds_area(radial_bounds)
    original_radius_avg = sum(node.radius for node in nodes) / len(nodes)
    radial_radius_avg = sum(node.radial_radius for node in nodes) / len(nodes)
    displacement_avg = (
        sum(math.hypot(node.radial_x - node.x, node.radial_y - node.y) for node in nodes)
        / len(nodes)
    )

    stats.updated_nodes = len(nodes)
    stats.metrics = {
        "original_area": round(original_area, 2),
        "radial_area": round(radial_area, 2),
        "area_ratio": round(radial_area / original_area, 4),
        "original_avg_radius": round(original_radius_avg, 2),
        "radial_avg_radius": round(radial_radius_avg, 2),
        "avg_radius_ratio": round(radial_radius_avg / max(1.0, original_radius_avg), 4),
        "avg_displacement": round(displacement_avg, 2),
        "max_angle_delta_degrees": round(
            max(node.angle_delta for node in nodes) * 180 / math.pi,
            3,
        ),
        "outward_nodes": outward_count,
        "overlap_repairs": 0,
        "max_original_radius": round(max_seen_radius, 2),
    }
    stats.sample = [
        {
            "title": node.title,
            "x": round(node.x, 1),
            "y": round(node.y, 1),
            "radial_x": round(node.radial_x, 1),
            "radial_y": round(node.radial_y, 1),
            "radius_ratio": round(node.radial_radius / max(1.0, node.radius), 3),
        }
        for node in sorted(nodes, key=lambda item: (item.radius, item.title.lower()))[:12]
    ]
    return stats


def _coerce_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _fetch_layout_nodes(conn: Any, *, layout_key: str) -> list[CompactNode]:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT
                        layout.genre_id,
                        genre.wikipedia_title,
                        layout.x,
                        layout.y,
                        layout.width,
                        layout.height,
                        layout.box_width,
                        layout.box_height,
                        layout.box_pad_x,
                        layout.box_pad_y,
                        layout.priority,
                        layout.lod_score,
                        layout.lod_rank,
                        layout.metadata
                    FROM wg_genre_semantic_layouts layout
                    JOIN wg_genres genre ON genre.id = layout.genre_id
                    WHERE layout.layout_key = :layout_key
                    ORDER BY layout.genre_id
                """),
                {"layout_key": layout_key},
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        CompactNode(
            genre_id=row["genre_id"],
            title=row["wikipedia_title"],
            x=float(row["x"]),
            y=float(row["y"]),
            width=float(row["width"]),
            height=float(row["height"]),
            box_width=float(row["box_width"] or (float(row["width"]) + LABEL_PAD_X * 2)),
            box_height=float(row["box_height"] or (float(row["height"]) + LABEL_PAD_Y * 2)),
            box_pad_x=float(row["box_pad_x"] or LABEL_PAD_X),
            box_pad_y=float(row["box_pad_y"] or LABEL_PAD_Y),
            priority=float(row["priority"]),
            lod_score=float(row["lod_score"] or 0.0),
            lod_rank=int(row["lod_rank"] or 0),
            metadata=_coerce_metadata(row["metadata"]),
        )
        for row in rows
    ]


async def compact_semantic_cloud_layout_radially(
    *,
    root_genre_id: str | None = None,
    dry_run: bool = False,
    sample_size: int = 12,
    lanes: int = 96,
    radius_step: float = 8.0,
    angular_steps: int = 8,
    inner_radius: float = 0.0,
) -> RadialCompactionStats:
    """Compute and optionally store radial compacted coordinates for one layout."""
    await apply_migrations()
    engine = get_engine()
    layout_key = layout_key_for_root(root_genre_id)
    async with engine.connect() as conn:
        nodes = await _fetch_layout_nodes(conn, layout_key=layout_key)

    stats = compact_nodes_radially(
        nodes,
        lanes=lanes,
        radius_step=radius_step,
        angular_steps=angular_steps,
        inner_radius=inner_radius,
    )
    stats.layout_key = layout_key
    stats.dry_run = dry_run
    stats.sample = stats.sample[:sample_size]

    if dry_run:
        logger.info(
            "radial_cloud_compaction_dry_run",
            layout_key=layout_key,
            total_nodes=stats.total_nodes,
            metrics=stats.metrics,
        )
        return stats

    quality_json = json.dumps(
        {
            "version": COMPACTION_VERSION,
            "metrics": stats.metrics,
        },
        sort_keys=True,
    )
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE wg_genre_semantic_layouts
                SET
                    radial_x = :radial_x,
                    radial_y = :radial_y,
                    box_width = :box_width,
                    box_height = :box_height,
                    box_pad_x = :box_pad_x,
                    box_pad_y = :box_pad_y,
                    radial_compaction_version = :version,
                    radial_compaction_quality = CAST(:quality AS jsonb),
                    radial_compacted_at = now()
                WHERE layout_key = :layout_key
                  AND genre_id = :genre_id
            """),
            [
                {
                    "layout_key": layout_key,
                    "genre_id": node.genre_id,
                    "radial_x": node.radial_x,
                    "radial_y": node.radial_y,
                    "box_width": node.box_width,
                    "box_height": node.box_height,
                    "box_pad_x": node.box_pad_x,
                    "box_pad_y": node.box_pad_y,
                    "version": COMPACTION_VERSION,
                    "quality": quality_json,
                }
                for node in nodes
            ],
        )

    logger.info(
        "radial_cloud_compaction_complete",
        layout_key=layout_key,
        total_nodes=stats.total_nodes,
        updated_nodes=stats.updated_nodes,
        area_ratio=stats.metrics.get("area_ratio"),
        avg_radius_ratio=stats.metrics.get("avg_radius_ratio"),
    )
    return stats
