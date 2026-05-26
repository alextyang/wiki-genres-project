from __future__ import annotations

from wiki_genres.loader.genre_direction_guard import DirectionEdge, should_ignore_wrong_direction


def edge(
    *,
    from_title: str,
    to_title: str,
    relation: str = "derivative",
    source: str = "wikidata",
    from_views: int = 100,
    to_views: int = 1000,
) -> DirectionEdge:
    return DirectionEdge(
        from_genre_id="from",
        to_genre_id="to",
        from_title=from_title,
        to_title=to_title,
        relation=relation,
        source=source,
        ordinal=0,
        evidence_relation=relation,
        from_views=from_views,
        to_views=to_views,
    )


def test_direction_guard_suppresses_specific_to_broad_reverse_edge() -> None:
    assert should_ignore_wrong_direction(
        edge(from_title="C-pop", to_title="Rhythm and blues", from_views=165, to_views=1364)
    )


def test_direction_guard_preserves_specific_to_specific_edge() -> None:
    assert not should_ignore_wrong_direction(
        edge(from_title="C-pop", to_title="Mandopop", from_views=165, to_views=200)
    )


def test_direction_guard_preserves_manual_curation() -> None:
    assert not should_ignore_wrong_direction(
        edge(from_title="C-pop", to_title="Rhythm and blues", source="manual_curation")
    )
