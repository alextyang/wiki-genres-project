"""Tests for inbound relationship indexer graph rules."""

from wiki_genres.loader.inbound_indexer import (
    DISPLAY_RELATIONS,
    FUSION_RELATION,
    RELATED_RELATION,
    _build_adjacency,
    _has_path,
    _is_excluded_parent,
    _reverse_coverage_relation,
    _reverse_evidence_relation,
    _summary_supported_reverse_relation,
)


def test_has_path_requires_min_depth_for_ancestor_shortcuts() -> None:
    adjacency = _build_adjacency(
        [
            ("pop", "dance-pop"),
            ("dance-pop", "bubblegum-dance"),
        ]
    )

    assert _has_path(adjacency, "pop", "bubblegum-dance", min_depth=2)
    assert not _has_path(adjacency, "pop", "dance-pop", min_depth=2)


def test_candidate_subclass_graph_can_suppress_broad_parent_shortcut() -> None:
    adjacency = _build_adjacency(
        [
            ("pop", "dance-pop"),
            ("dance-pop", "bubblegum-dance"),
            ("pop", "bubblegum-dance"),
        ]
    )

    assert _has_path(adjacency, "pop", "bubblegum-dance", min_depth=2)


def test_has_path_handles_cycles() -> None:
    adjacency = _build_adjacency(
        [
            ("a", "b"),
            ("b", "a"),
            ("b", "c"),
        ]
    )

    assert _has_path(adjacency, "a", "c", min_depth=1)
    assert not _has_path(adjacency, "c", "a", min_depth=1)


def test_abstract_music_classifier_parents_are_excluded() -> None:
    assert _is_excluded_parent("Q188451", "Music genre")
    assert _is_excluded_parent("Q2944929", "Musical style")
    assert not _is_excluded_parent("Q37073", "Pop music")


def test_related_genre_is_not_a_display_relation() -> None:
    assert RELATED_RELATION not in DISPLAY_RELATIONS
    assert FUSION_RELATION in DISPLAY_RELATIONS


def test_reverse_fusion_coverage_is_not_display_relation() -> None:
    """Fusion is visible only in source/component -> fusion-child direction."""
    relation = _reverse_coverage_relation(FUSION_RELATION)

    assert relation == RELATED_RELATION
    assert relation not in DISPLAY_RELATIONS


def test_reverse_coverage_evidence_uses_inverse_labels() -> None:
    assert _reverse_evidence_relation("subgenre") == "subgenre_of"
    assert _reverse_evidence_relation("derivative") == "derivative_of"
    assert _reverse_evidence_relation(FUSION_RELATION) == "fusion_of"
    assert _reverse_evidence_relation("stylistic_origin") == "stylistic_origin_of"


def test_summary_phrase_promotes_subgenre_parent() -> None:
    summary = "Latin Christian music is a subgenre of Latin music and Contemporary Christian music."

    assert (
        _summary_supported_reverse_relation(summary, "Latin Christian music", "Latin music")
        == "subgenre"
    )
    assert (
        _summary_supported_reverse_relation(
            summary,
            "Latin Christian music",
            "Contemporary Christian music",
        )
        == "subgenre"
    )


def test_summary_kind_of_phrase_matches_parent_inside_expanded_noun_phrase() -> None:
    summary = (
        "Starogradska muzika is a kind of urban traditional folk music found "
        "in Bulgaria, North Macedonia and Serbia."
    )

    assert (
        _summary_supported_reverse_relation(summary, "Starogradska muzika", "Folk music")
        == "subgenre"
    )


def test_summary_phrase_does_not_promote_origin_mentions_after_clause_boundary() -> None:
    summary = "Example music is a genre of popular music that originated from blues."

    assert _summary_supported_reverse_relation(summary, "Example music", "Blues") is None
