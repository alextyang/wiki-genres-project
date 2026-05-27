from wiki_genres.loader.semantic_cloud_layout import (
    SemanticGenre,
    _assign_lod,
    _build_vectors,
    _layout,
    _merge_edges,
    layout_key_for_root,
)


def test_semantic_cloud_label_metrics_store_text_and_padded_boxes() -> None:
    genre = SemanticGenre(
        genre_id="wg-rb",
        title="Rhythm and blues",
        summary=None,
        monthly_views_p30=100,
        depth_from_music=2,
        root_genre_id="wg-root",
        root_title="Rhythm and blues",
        child_connection_count=3,
        parent_connection_count=2,
        has_playlist=True,
    )

    assert genre.text_width == genre.width
    assert genre.text_height == genre.height
    assert genre.box_width > genre.text_width
    assert genre.box_height > genre.text_height
    assert genre.box_pad_x > genre.box_pad_y


def test_semantic_cloud_filters_wikipedia_maintenance_terms() -> None:
    genre = SemanticGenre(
        genre_id="wg-test",
        title="Example folk",
        summary="A regional folk style with fiddles.",
        monthly_views_p30=10,
        depth_from_music=2,
        root_genre_id="wg-root",
        root_title="Folk music",
        child_connection_count=0,
        parent_connection_count=1,
        has_playlist=False,
        categories=[
            "Articles with dead external links",
            "Folk music genres",
            "Commons category link from Wikidata",
        ],
    )

    _build_vectors([genre])

    assert "folk" in genre.vector
    assert "dead_external" not in genre.terms
    assert "commons_category" not in genre.terms


def test_semantic_cloud_layout_keys_are_stable() -> None:
    assert layout_key_for_root(None) == "general_music_v1"
    assert layout_key_for_root("wg-q123") == "region:wg-q123:v1"


def test_semantic_cloud_layout_keeps_scoped_center_at_origin() -> None:
    center = SemanticGenre(
        genre_id="wg-root",
        title="Music of Testland",
        summary=None,
        monthly_views_p30=100,
        depth_from_music=1,
        root_genre_id="wg-root",
        root_title="Music of Testland",
        child_connection_count=2,
        parent_connection_count=0,
        has_playlist=False,
    )
    child = SemanticGenre(
        genre_id="wg-child",
        title="Testland fiddle",
        summary="A fiddle dance style.",
        monthly_views_p30=50,
        depth_from_music=2,
        root_genre_id="wg-root",
        root_title="Music of Testland",
        child_connection_count=0,
        parent_connection_count=1,
        has_playlist=True,
    )
    _build_vectors([center, child])

    _layout([center, child], _merge_edges([]), center_genre_id="wg-root", iterations=3)

    assert center.x == 0
    assert center.y == 0
    assert child.x or child.y


def test_semantic_cloud_lod_scores_are_stable_and_progressive() -> None:
    genres = [
        SemanticGenre(
            genre_id=f"wg-{index}",
            title=f"Genre {index}",
            summary=None,
            monthly_views_p30=100 - index,
            depth_from_music=3,
            root_genre_id="wg-root",
            root_title="Rock music",
            child_connection_count=0,
            parent_connection_count=1,
            has_playlist=False,
        )
        for index in range(20)
    ]

    _assign_lod(genres, center_genre_id=None)

    ranked = sorted(genres, key=lambda genre: genre.lod_rank)
    assert ranked[0].title == "Genre 0"
    assert ranked[-1].title == "Genre 19"
    assert ranked[0].lod_score > ranked[-1].lod_score
    assert [genre.lod_rank for genre in ranked] == list(range(20))
    assert all(0 <= genre.lod_score <= 1 for genre in genres)
    assert all(genre.show_scale >= genre.hide_scale for genre in genres)


def test_semantic_cloud_lod_penalizes_long_labels() -> None:
    concise = SemanticGenre(
        genre_id="wg-concise",
        title="Rock",
        summary=None,
        monthly_views_p30=100,
        depth_from_music=3,
        root_genre_id="wg-root",
        root_title="Rock music",
        child_connection_count=1,
        parent_connection_count=1,
        has_playlist=False,
    )
    verbose = SemanticGenre(
        genre_id="wg-verbose",
        title="Very Specific Regional Rock Fusion",
        summary=None,
        monthly_views_p30=100,
        depth_from_music=3,
        root_genre_id="wg-root",
        root_title="Rock music",
        child_connection_count=1,
        parent_connection_count=1,
        has_playlist=False,
    )

    _assign_lod([concise, verbose], center_genre_id=None)

    assert concise.lod_score > verbose.lod_score
    assert concise.lod_rank < verbose.lod_rank
