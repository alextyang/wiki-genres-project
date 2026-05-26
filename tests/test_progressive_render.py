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
    assert snapshots[1]["stream"]["layer"] == "tier:1"
    assert snapshots[-1]["stream"]["complete"] is True
    assert snapshots[-1]["stats"]["layers"] == [
        {"lod_tier": 0, "nodes": 1},
        {"lod_tier": 1, "nodes": 1},
        {"lod_tier": 2, "nodes": 1},
        {"lod_tier": 4, "nodes": 1},
    ]


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
