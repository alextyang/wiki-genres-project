import math

from wiki_genres.api.routes.genres import (
    _apply_cloud_selected_distances,
    _apply_materialized_cloud_layout,
    _cloud_selected_distance_map,
    _cull_cloud_nodes,
)
from wiki_genres.loader.radial_cloud_compaction import (
    CENTER_LABEL_HEIGHT,
    CENTER_LABEL_WIDTH,
    CompactNode,
    _rect_for,
    _rects_overlap,
    compact_nodes_radially,
)


def _sample_nodes() -> list[CompactNode]:
    nodes: list[CompactNode] = []
    for index in range(36):
        angle = (index / 36) * math.tau
        radius = 420 + (index % 6) * 125
        nodes.append(
            CompactNode(
                genre_id=f"wg-{index}",
                title=f"Genre {index}",
                x=math.cos(angle) * radius,
                y=math.sin(angle) * radius,
                width=70 + (index % 4) * 12,
                height=16,
                box_width=70 + (index % 4) * 12 + 10,
                box_height=16 + 8,
                box_pad_x=5,
                box_pad_y=4,
                lod_rank=index,
                lod_score=1 - index / 100,
                priority=1000 - index,
                metadata={"root_title": f"Root {index % 6}"},
            )
        )
    return nodes


def test_radial_compaction_packs_inward_without_mutating_anchors() -> None:
    nodes = _sample_nodes()
    anchors = {node.genre_id: (node.x, node.y) for node in nodes}

    stats = compact_nodes_radially(nodes, lanes=48, radius_step=12, angular_steps=3)

    assert stats.updated_nodes == len(nodes)
    assert stats.metrics["avg_radius_ratio"] < 1
    assert stats.metrics["area_ratio"] < 1
    assert all((node.x, node.y) == anchors[node.genre_id] for node in nodes)


def test_radial_compaction_outputs_non_overlapping_rectangles() -> None:
    nodes = _sample_nodes()

    compact_nodes_radially(nodes, lanes=48, radius_step=12, angular_steps=3)

    rects = [_rect_for(0, 0, CENTER_LABEL_WIDTH, CENTER_LABEL_HEIGHT)]
    rects.extend(
        _rect_for(node.radial_x, node.radial_y, node.box_width, node.box_height) for node in nodes
    )
    for index, rect in enumerate(rects):
        assert not any(_rects_overlap(rect, other) for other in rects[index + 1 :])


def test_cloud_layout_helper_uses_radial_coordinates_for_display() -> None:
    nodes = [{"id": "wg-a", "label": "A", "x": 0, "y": 0, "width": 10, "height": 10}]
    layout_rows = [
        {
            "genre_id": "wg-a",
            "x": 100,
            "y": 200,
            "radial_x": 12,
            "radial_y": 34,
            "width": 20,
            "height": 10,
            "text_width": 20,
            "text_height": 10,
            "box_width": 30,
            "box_height": 18,
            "box_pad_x": 5,
            "box_pad_y": 4,
            "priority": 1,
            "lod_score": 0.5,
            "lod_rank": 2,
            "lod_tier": 1,
        }
    ]

    laid_out, materialized, radial = _apply_materialized_cloud_layout(nodes, layout_rows)

    assert materialized == 1
    assert radial == 1
    assert laid_out[0]["x"] == 12
    assert laid_out[0]["y"] == 34
    assert laid_out[0]["radial_x"] == 12
    assert laid_out[0]["radial_y"] == 34


def test_cloud_culling_keeps_all_scale_one_nodes_when_boxes_do_not_overlap() -> None:
    nodes = [
        {
            "id": "a",
            "label": "Alpha",
            "x": -40,
            "y": 0,
            "width": 20,
            "height": 10,
            "box_width": 40,
            "box_height": 20,
            "lod_rank": 0,
            "lod_tier": 0,
            "lod_score": 1.0,
            "priority": 10,
        },
        {
            "id": "b",
            "label": "Beta",
            "x": 40,
            "y": 0,
            "width": 20,
            "height": 10,
            "box_width": 40,
            "box_height": 20,
            "lod_rank": 1,
            "lod_tier": 0,
            "lod_score": 0.8,
            "priority": 9,
        },
    ]

    visible = _cull_cloud_nodes(
        nodes,
        x_min=None,
        x_max=None,
        y_min=None,
        y_max=None,
        scale=1.0,
        view_tx=0,
        view_ty=0,
        selected_genre_id=None,
        limit=None,
    )

    assert [node["id"] for node in visible] == ["a", "b"]


def test_cloud_culling_hides_only_lower_priority_node_when_zoom_creates_overlap() -> None:
    nodes = [
        {
            "id": "a",
            "label": "Alpha",
            "x": -20,
            "y": 0,
            "width": 20,
            "height": 10,
            "box_width": 40,
            "box_height": 20,
            "lod_rank": 0,
            "lod_tier": 0,
            "lod_score": 1.0,
            "priority": 10,
        },
        {
            "id": "b",
            "label": "Beta",
            "x": 20,
            "y": 0,
            "width": 20,
            "height": 10,
            "box_width": 40,
            "box_height": 20,
            "lod_rank": 1,
            "lod_tier": 0,
            "lod_score": 0.8,
            "priority": 9,
        },
    ]

    visible = _cull_cloud_nodes(
        nodes,
        x_min=None,
        x_max=None,
        y_min=None,
        y_max=None,
        scale=0.95,
        view_tx=0,
        view_ty=0,
        selected_genre_id=None,
        limit=None,
    )

    assert [node["id"] for node in visible] == ["a"]


def test_cloud_selected_distance_map_walks_semantic_edges_undirected() -> None:
    edges = [
        {"from_genre_id": "selected", "to_genre_id": "direct", "weight": 0.9},
        {"from_genre_id": "second", "to_genre_id": "direct", "weight": 0.4},
        {"from_genre_id": "unrelated", "to_genre_id": "elsewhere", "weight": 1.0},
    ]

    distances = _cloud_selected_distance_map(edges, selected_genre_id="selected")

    assert distances["selected"]["distance"] == 0
    assert distances["direct"]["distance"] == 1
    assert distances["second"]["distance"] == 2
    assert "unrelated" not in distances
    assert distances["direct"]["score"] > distances["second"]["score"]


def test_apply_cloud_selected_distances_preserves_unrelated_nodes() -> None:
    nodes = [{"id": "selected"}, {"id": "direct"}, {"id": "unrelated"}]
    distances = {
        "selected": {"distance": 0, "score": 1.0},
        "direct": {"distance": 1, "score": 0.8},
    }

    applied = _apply_cloud_selected_distances(nodes, distances)

    assert applied[0]["selected_distance"] == 0
    assert applied[1]["selected_distance"] == 1
    assert applied[1]["selected_focus_score"] == 0.8
    assert "selected_distance" not in applied[2]
