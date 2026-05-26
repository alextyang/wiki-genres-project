"""Tests for cycle-guard traversal."""

from wiki_genres.loader.cycle_guard import (
    EdgeKey,
    TraversalEdge,
    _build_adjacency,
    find_cycle_edges,
)


def edge(
    from_id: str,
    to_id: str,
    ordinal: int = 0,
    relation: str = "subgenre",
    evidence_relation: str | None = None,
    source: str = "infobox",
) -> TraversalEdge:
    return TraversalEdge(
        key=EdgeKey(
            from_genre_id=from_id,
            relation=relation,
            source=source,
            ordinal=ordinal,
        ),
        to_genre_id=to_id,
        from_title=from_id.title(),
        to_title=to_id.title(),
        evidence_relation=evidence_relation,
    )


def test_find_cycle_edges_flags_back_edge_to_current_path() -> None:
    edges = [
        edge("music", "rock"),
        edge("rock", "metal"),
        edge("metal", "rock", ordinal=1),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(edges),
        {node: node.title() for node in ["music", "rock", "metal"]},
    )

    assert ignored == [edges[2].key]
    assert samples[0].path_titles == ["Rock", "Metal", "Rock"]
    assert visited == 3


def test_find_cycle_edges_allows_cross_links_to_completed_nodes() -> None:
    edges = [
        edge("music", "rock"),
        edge("rock", "metal"),
        edge("music", "pop", ordinal=1),
        edge("pop", "metal"),
    ]

    ignored, samples, _visited = find_cycle_edges(
        ["music"],
        _build_adjacency(edges),
        {node: node.title() for node in ["music", "rock", "metal", "pop"]},
    )

    assert ignored == []
    assert samples == []


def test_find_cycle_edges_starts_from_multiple_music_roots() -> None:
    edges = [
        edge("jazz", "fusion"),
        edge("fusion", "jazz"),
        edge("rock", "prog"),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["rock", "jazz"],
        _build_adjacency(edges),
        {node: node.title() for node in ["rock", "prog", "jazz", "fusion"]},
    )

    assert ignored == [edges[1].key]
    assert samples[0].path_titles == ["Jazz", "Fusion", "Jazz"]
    assert visited == 4


def test_find_cycle_edges_can_flag_non_traversal_back_reference() -> None:
    traversal_edges = [
        edge("music", "hip-hop"),
        edge("hip-hop", "grime"),
    ]
    relationship_edges = [
        *traversal_edges,
        edge(
            "grime",
            "hip-hop",
            ordinal=2,
            relation="related_genre",
            evidence_relation="fusion_genre",
        ),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(traversal_edges),
        {node: node.title() for node in ["music", "hip-hop", "grime"]},
        check_adjacency=_build_adjacency(relationship_edges),
    )

    assert ignored == [relationship_edges[2].key]
    assert samples[0].path_titles == ["Hip-Hop", "Grime", "Hip-Hop"]
    assert visited == 3


def test_find_cycle_edges_does_not_flag_distant_non_traversal_ancestor() -> None:
    traversal_edges = [
        edge("music", "rock"),
        edge("rock", "acid-rock"),
        edge("acid-rock", "hard-rock"),
    ]
    relationship_edges = [
        *traversal_edges,
        edge("hard-rock", "rock", ordinal=3, relation="stylistic_origin"),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(traversal_edges),
        {node: node.title() for node in ["music", "rock", "acid-rock", "hard-rock"]},
        check_adjacency=_build_adjacency(relationship_edges),
    )

    assert ignored == []
    assert samples == []
    assert visited == 4


def test_find_cycle_edges_preserves_original_non_traversal_back_reference() -> None:
    traversal_edges = [
        edge("music", "hip-hop"),
        edge("hip-hop", "grime"),
    ]
    relationship_edges = [
        *traversal_edges,
        edge("grime", "hip-hop", ordinal=2, relation="stylistic_origin"),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(traversal_edges),
        {node: node.title() for node in ["music", "hip-hop", "grime"]},
        check_adjacency=_build_adjacency(relationship_edges),
    )

    assert ignored == []
    assert samples == []
    assert visited == 3


def test_find_cycle_edges_flags_direct_related_backref_after_shared_visit() -> None:
    traversal_edges = [
        edge("music", "garage"),
        edge("garage", "grime"),
        edge("hip-hop", "grime", ordinal=1),
    ]
    relationship_edges = [
        *traversal_edges,
        edge(
            "grime",
            "hip-hop",
            ordinal=2,
            relation="related_genre",
            evidence_relation="fusion_genre",
        ),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music", "hip-hop"],
        _build_adjacency(traversal_edges),
        {node: node.title() for node in ["music", "garage", "hip-hop", "grime"]},
        check_adjacency=_build_adjacency(relationship_edges),
    )

    assert ignored == [relationship_edges[3].key]
    assert samples[0].path_titles == ["Hip-Hop", "Grime", "Hip-Hop"]
    assert visited == 4


def test_related_genre_with_display_evidence_is_traversable() -> None:
    edges = [
        edge("music", "rock"),
        edge(
            "rock",
            "fusion",
            relation="related_genre",
            evidence_relation="fusion_genre",
        ),
        edge("fusion", "rock", ordinal=2),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(edges),
        {node: node.title() for node in ["music", "rock", "fusion"]},
    )

    assert ignored == [edges[2].key]
    assert samples[0].path_titles == ["Rock", "Fusion", "Rock"]
    assert visited == 3


def test_related_genre_without_display_evidence_is_not_traversable() -> None:
    edges = [
        edge("music", "rock"),
        edge("rock", "fusion", relation="related_genre"),
        edge("fusion", "rock", ordinal=2),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency([edge for edge in edges if edge.is_display_relationship]),
        {node: node.title() for node in ["music", "rock", "fusion"]},
        check_adjacency=_build_adjacency(edges),
    )

    assert ignored == []
    assert samples == []
    assert visited == 2


def test_find_cycle_edges_preserves_manual_curation_mounts() -> None:
    edges = [
        edge("ghazal", "music-of-india"),
        edge("music-of-india", "ghazal", ordinal=1, source="manual_curation"),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["ghazal"],
        _build_adjacency(edges),
        {node: node.title() for node in ["ghazal", "music-of-india"]},
    )

    assert ignored == []
    assert samples == []
    assert visited == 2


def test_summary_confirmed_reverse_edge_wins_over_opposite_infobox_edge() -> None:
    edges = [
        edge("music", "latin-christian"),
        edge("latin-christian", "latin", ordinal=1, source="infobox"),
        edge(
            "latin",
            "latin-christian",
            ordinal=2,
            source="inbound_index",
            evidence_relation="summary_subgenre_of",
        ),
    ]

    ignored, samples, visited = find_cycle_edges(
        ["music"],
        _build_adjacency(edges),
        {node: node.title() for node in ["music", "latin-christian", "latin"]},
    )

    assert ignored == [edges[1].key]
    assert samples[0].edge == edges[1]
    assert visited == 3
