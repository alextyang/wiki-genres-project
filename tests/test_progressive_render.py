"""Progressive render stream helpers."""

from __future__ import annotations

from wiki_genres.api.routes.render import _cloud_snapshots, _filter_timeline_viewport, _timeline_snapshots


def test_cloud_snapshots_are_layered_and_prioritized() -> None:
    data = {
        "nodes": [
            {"id": "low", "label": "Low", "lod_tier": 2, "lod_rank": 2, "lod_score": 0.1},
            {"id": "selected", "label": "Selected", "lod_tier": 4, "lod_rank": 4, "lod_score": 0},
            {"id": "__music_root__", "label": "Music", "lod_tier": 0, "lod_rank": -1, "lod_score": 1},
            {"id": "high", "label": "High", "lod_tier": 1, "lod_rank": 1, "lod_score": 0.9},
        ],
        "stats": {"total_nodes": 4},
    }

    snapshots = _cloud_snapshots(data, selected_genre_id="selected", chunk_size=2)

    assert {node["id"] for node in snapshots[0]["nodes"]} == {"__music_root__", "selected"}
    assert snapshots[0]["stream"]["atlas"] is True
    assert snapshots[0]["stream"]["kind"] == "catalog"
    assert snapshots[1]["stream"]["kind"] == "catalog"
    scale_snapshots = [
        snapshot for snapshot in snapshots if snapshot["stream"].get("kind") == "scale_layer"
    ]
    assert scale_snapshots
    assert scale_snapshots[0]["stream"]["layer"] == "scale:0.12"
    assert scale_snapshots[0]["stream"]["atlas_version"] == "cloud-render-atlas-v2"
    assert scale_snapshots[0]["stream"]["tile_size"] > 0
    assert scale_snapshots[0]["stream"]["tiles"]
    assert all("node_ids" in tile for tile in scale_snapshots[0]["stream"]["tiles"])
    materialized: set[str] = set()
    for snapshot in scale_snapshots:
        stream = snapshot["stream"]
        assert stream["delta"] is True
        materialized.update(stream.get("add_node_ids") or stream.get("visible_node_ids") or [])
        materialized.difference_update(stream.get("remove_node_ids") or [])
    assert materialized == {
        "__music_root__",
        "high",
        "low",
        "selected",
    }
    assert snapshots[-1]["stream"]["complete"] is True
    assert snapshots[-1]["stats"]["scale_layers"][-1] == {"scale": 1.0, "nodes": 4}


def test_cloud_snapshots_keep_anchors_before_selected_relationship_tiers() -> None:
    data = {
        "nodes": [
            {
                "id": "__music_root__",
                "label": "Music",
                "lod_rank": -1,
                "lod_tier": 0,
                "lod_score": 1,
                "x": 0,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
            {
                "id": "selected",
                "label": "Selected",
                "selected_distance": 0,
                "lod_rank": 50,
                "lod_tier": 5,
                "lod_score": 0,
                "x": 1000,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
            {
                "id": "direct-over-root",
                "label": "Direct Over Root",
                "selected_distance": 1,
                "lod_rank": 0,
                "lod_tier": 0,
                "lod_score": 1,
                "x": 0,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
            {
                "id": "direct",
                "label": "Direct",
                "selected_distance": 1,
                "lod_rank": 80,
                "lod_tier": 5,
                "lod_score": 0,
                "x": 2000,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
            {
                "id": "second",
                "label": "Second",
                "selected_distance": 2,
                "lod_rank": 0,
                "lod_tier": 0,
                "lod_score": 1,
                "x": 3000,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
            {
                "id": "unrelated",
                "label": "Unrelated",
                "lod_rank": 0,
                "lod_tier": 0,
                "lod_score": 1,
                "x": 4000,
                "y": 0,
                "box_width": 120,
                "box_height": 32,
            },
        ],
        "stats": {"total_nodes": 6},
    }

    snapshots = _cloud_snapshots(data, selected_genre_id="selected", chunk_size=5)

    assert [node["id"] for node in snapshots[0]["nodes"]] == [
        "selected",
        "__music_root__",
        "direct-over-root",
        "direct",
        "second",
    ]
    first_scale_snapshot = next(
        snapshot for snapshot in snapshots if snapshot["stream"].get("kind") == "scale_layer"
    )
    assert "__music_root__" in first_scale_snapshot["stream"]["add_node_ids"]
    assert "direct" in first_scale_snapshot["stream"]["add_node_ids"]
    assert "direct-over-root" not in first_scale_snapshot["stream"]["add_node_ids"]
    first_layer_tile_ids = {
        node_id
        for tile in first_scale_snapshot["stream"]["tiles"]
        for node_id in tile["node_ids"]
    }
    assert first_layer_tile_ids == set(first_scale_snapshot["stream"]["add_node_ids"])


def test_timeline_snapshots_include_only_edges_with_streamed_endpoints() -> None:
    data = {
        "nodes": [
            {"id": "a", "wikipedia_title": "A", "x": 0, "y": 0, "timeline_rank": 0.1},
            {"id": "b", "wikipedia_title": "B", "x": 100, "y": 20, "timeline_rank": 0.2},
            {"id": "c", "wikipedia_title": "C", "x": 200, "y": 40, "timeline_rank": 0.3},
        ],
        "edges": [
            {"from_genre_id": "a", "to_genre_id": "b", "relation": "subgenre", "source": "x", "route": []},
            {"from_genre_id": "b", "to_genre_id": "c", "relation": "subgenre", "source": "x", "route": []},
        ],
        "stats": {"total_nodes": 3, "total_edges": 2},
    }

    snapshots = _timeline_snapshots(data, selected_genre_id="a", chunk_size=2)

    assert [node["id"] for node in snapshots[0]["nodes"]] == ["a", "b"]
    assert len(snapshots[0]["edges"]) == 1
    assert len(snapshots[-1]["edges"]) == 2
    assert snapshots[-1]["stats"]["bounds"] == {
        "min_x": 0.0,
        "max_x": 200.0,
        "min_y": 0.0,
        "max_y": 40.0,
    }
    assert "render_scene" in snapshots[-1]
    assert snapshots[-1]["render_scene"]["edges"][0]["path"].startswith("M ")


def test_timeline_viewport_filter_keeps_full_bounds_and_selected_node() -> None:
    data = {
        "nodes": [
            {"id": "selected", "wikipedia_title": "Selected", "x": 500, "y": 500},
            {"id": "visible", "wikipedia_title": "Visible", "x": 10, "y": 20},
            {"id": "hidden", "wikipedia_title": "Hidden", "x": 900, "y": 20},
        ],
        "edges": [
            {"from_genre_id": "selected", "to_genre_id": "visible", "relation": "subgenre", "source": "x", "route": []},
            {"from_genre_id": "visible", "to_genre_id": "hidden", "relation": "subgenre", "source": "x", "route": []},
        ],
        "stats": {},
    }

    filtered = _filter_timeline_viewport(
        data,
        x_min=0,
        x_max=100,
        y_min=0,
        y_max=100,
        selected_genre_id="selected",
    )

    assert [node["id"] for node in filtered["nodes"]] == ["selected", "visible"]
    assert len(filtered["edges"]) == 1
    assert filtered["stats"]["bounds"]["max_x"] == 900.0
