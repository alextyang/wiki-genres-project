"""Tests for Music-root reachability indexing rules."""

from wiki_genres.loader.music_reachability import (
    MUSIC_COUNTRY_ROOT_SOURCE,
    MUSIC_ROOT_ID,
    ORIGIN_PARENT_RELATION,
    OrphanGenre,
    ReachabilityEdge,
    RootGenre,
    SUPPLEMENTAL_MUSIC_ROOT_SOURCE,
    compute_orphan_genres,
    compute_reachable_parents,
)


def edge(parent: str, child: str, relation: str = "subgenre") -> ReachabilityEdge:
    return ReachabilityEdge(
        from_genre_id=parent,
        to_genre_id=child,
        relation=relation,
        source="test",
        ordinal=0,
        from_title=parent.title(),
        to_title=child.title(),
    )


def related_edge(parent: str, child: str, evidence_relation: str) -> ReachabilityEdge:
    return ReachabilityEdge(
        from_genre_id=parent,
        to_genre_id=child,
        relation="related_genre",
        source="test",
        ordinal=0,
        from_title=parent.title(),
        to_title=child.title(),
        evidence_relation=evidence_relation,
    )


def test_indexes_all_reachable_parents_with_parent_depth() -> None:
    roots = [RootGenre("rock", "Rock", 0)]
    _, rows, skipped_cycles, _, _ = compute_reachable_parents(
        roots,
        [
            edge("rock", "metal"),
            edge("rock", "black-metal"),
            edge("metal", "black-metal"),
        ],
    )

    keyed = {(row.parent_genre_id, row.genre_id): row for row in rows}

    assert keyed[(MUSIC_ROOT_ID, "rock")].parent_depth_from_music == 0
    assert keyed[("rock", "metal")].parent_depth_from_music == 1
    assert keyed[("rock", "metal")].depth_from_music == 2
    assert keyed[("rock", "black-metal")].parent_depth_from_music == 1
    assert keyed[("metal", "black-metal")].parent_depth_from_music == 2
    assert keyed[("metal", "black-metal")].path_genre_ids == (
        "rock",
        "metal",
        "black-metal",
    )
    assert skipped_cycles == 0


def test_hidden_country_root_keeps_music_parent_but_distinct_source() -> None:
    roots = [RootGenre("music-of-tuvalu", "Music of Tuvalu", 15, MUSIC_COUNTRY_ROOT_SOURCE)]
    states, rows, _, _, _ = compute_reachable_parents(roots, [])

    assert states["music-of-tuvalu"].depth_from_music == 1
    root_parent = rows[0]
    assert root_parent.genre_id == "music-of-tuvalu"
    assert root_parent.parent_genre_id == MUSIC_ROOT_ID
    assert root_parent.parent_relation == "music_root"
    assert root_parent.parent_source == MUSIC_COUNTRY_ROOT_SOURCE


def test_supplemental_root_keeps_music_parent_but_distinct_source() -> None:
    roots = [
        RootGenre(
            "indigenous-music",
            "Indigenous music",
            16,
            SUPPLEMENTAL_MUSIC_ROOT_SOURCE,
        )
    ]
    states, rows, _, _, _ = compute_reachable_parents(roots, [])

    assert states["indigenous-music"].depth_from_music == 1
    assert rows[0].parent_genre_id == MUSIC_ROOT_ID
    assert rows[0].parent_source == SUPPLEMENTAL_MUSIC_ROOT_SOURCE


def test_canonical_node_depth_prefers_shortest_path_but_keeps_longer_parent() -> None:
    roots = [RootGenre("rock", "Rock", 0)]
    states, rows, _, _, _ = compute_reachable_parents(
        roots,
        [
            edge("rock", "metal"),
            edge("metal", "black-metal"),
            edge("rock", "black-metal"),
        ],
    )

    black_metal = states["black-metal"]
    assert black_metal.depth_from_music == 2
    assert black_metal.path_genre_ids == ("rock", "black-metal")

    longer_parent = next(
        row for row in rows if row.parent_genre_id == "metal" and row.genre_id == "black-metal"
    )
    assert longer_parent.parent_depth_from_music == 2
    assert longer_parent.depth_from_music == 3


def test_skips_edges_that_loop_back_into_parent_path() -> None:
    roots = [RootGenre("rock", "Rock", 0)]
    _, rows, skipped_cycles, _, _ = compute_reachable_parents(
        roots,
        [
            edge("rock", "metal"),
            edge("metal", "rock"),
        ],
    )

    assert skipped_cycles == 2
    assert {row.genre_id for row in rows} == {"rock", "metal"}
    assert all(row.parent_genre_id != "metal" or row.genre_id != "rock" for row in rows)


def test_respects_max_depth_for_parent_rows() -> None:
    roots = [RootGenre("rock", "Rock", 0)]
    states, rows, _, skipped_depth, _ = compute_reachable_parents(
        roots,
        [
            edge("rock", "metal"),
            edge("metal", "black-metal"),
        ],
        max_depth=2,
    )

    assert "black-metal" not in states
    assert ("metal", "black-metal") not in {(row.parent_genre_id, row.genre_id) for row in rows}
    assert skipped_depth >= 1


def test_related_genre_with_display_evidence_is_reachable_parent() -> None:
    roots = [RootGenre("rock", "Rock", 0)]
    states, rows, _, _, _ = compute_reachable_parents(
        roots,
        [
            related_edge("rock", "fusion", "fusion_genre"),
        ],
    )

    assert states["fusion"].depth_from_music == 2
    parent = next(row for row in rows if row.genre_id == "fusion")
    assert parent.parent_relation == "fusion_genre"
    assert parent.parent_source == "test"


def test_stylistic_origin_of_is_separate_origin_parent_relation() -> None:
    roots = [RootGenre("blues", "Blues", 0)]
    states, rows, _, _, _ = compute_reachable_parents(
        roots,
        [
            related_edge("blues", "rock", "stylistic_origin_of"),
        ],
    )

    assert states["rock"].depth_from_music == 2
    parent = next(row for row in rows if row.genre_id == "rock")
    assert parent.parent_relation == ORIGIN_PARENT_RELATION
    assert parent.path_genre_ids == ("blues", "rock")


def test_compute_orphan_genres_reports_unreachable_sorted_by_views() -> None:
    reachable, _, _, _, _ = compute_reachable_parents(
        [RootGenre("rock", "Rock", 0)],
        [edge("rock", "metal")],
    )

    count, sample = compute_orphan_genres(
        [
            OrphanGenre("rock", "Rock", 10),
            OrphanGenre("metal", "Metal", 5),
            OrphanGenre("orphan-low", "Orphan Low", 1),
            OrphanGenre("orphan-high", "Orphan High", 100),
        ],
        reachable,
        sample_size=1,
    )

    assert count == 2
    assert sample == [OrphanGenre("orphan-high", "Orphan High", 100)]
