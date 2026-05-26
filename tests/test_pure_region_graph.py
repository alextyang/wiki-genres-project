from wiki_genres.loader.pure_region_graph import (
    pure_region_relation_for_edge,
    region_mapping_from_title,
)


def test_region_mapping_from_title_includes_music_of_non_genre_pages() -> None:
    mapping = region_mapping_from_title("Music of Western Sahara", "wg-western-sahara")

    assert mapping is not None
    assert mapping.region_name == "Western Sahara"
    assert mapping.mapping_type == "title_music_of"


def test_region_mapping_from_title_includes_music_in_city_pages() -> None:
    mapping = region_mapping_from_title("Music in New York City", "wg-new-york-city")

    assert mapping is not None
    assert mapping.region_name == "New York City"
    assert mapping.mapping_type == "title_music_in"


def test_region_mapping_from_title_includes_music_categories() -> None:
    mapping = region_mapping_from_title("Category:Music of the Caribbean", "wg-caribbean")

    assert mapping is not None
    assert mapping.region_name == "Caribbean"
    assert mapping.mapping_type == "category_music_of"


def test_region_mapping_from_title_rejects_known_non_region_phrases() -> None:
    assert region_mapping_from_title("Music in advertising", "wg-advertising") is None
    assert region_mapping_from_title("Music in the Round", "wg-round") is None


def test_pure_region_relation_uses_region_kind_over_edge_label() -> None:
    assert (
        pure_region_relation_for_edge(
            source_edge_relation="subclass_of",
            from_region_kind="historical_region",
            source_direction="forward",
        )
        == "historical_region_of"
    )
    assert (
        pure_region_relation_for_edge(
            source_edge_relation="part_of",
            from_region_kind="city",
            source_direction="forward",
        )
        == "admin_parent"
    )
