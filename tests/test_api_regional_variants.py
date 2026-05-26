"""Tests for regional-variant response shaping."""

from wiki_genres.api.routes.genres import (
    REGION_PARENT_RELATIONS,
    _dedupe_map_selectables,
    _feature_key_for_region,
    _map_item_from_variant,
    _map_item_from_region_row,
    _region_name_from_music_title,
    _variant_from_regional_child_row,
    _variant_from_music_region_row,
)
from wiki_genres.api.models import MapRegionItemOut, RegionVariantOut


def test_music_of_title_strips_article_and_country_disambiguator() -> None:
    assert _region_name_from_music_title("Music of the Bahamas") == "Bahamas"
    assert _region_name_from_music_title("Music of Georgia (country)") == "Georgia"


def test_unknown_music_region_can_be_returned_without_static_coordinates() -> None:
    item = _variant_from_music_region_row(
        {
            "id": "wg-region",
            "wikipedia_title": "Music of Ecuador",
            "monthly_views_p30": 1200,
            "similarity_color": "#b96861",
            "color_confidence": 0.7,
        },
        match_type="music_region",
    )

    assert item is not None
    assert item.region_name == "Ecuador"
    assert item.region_key == "region-ecuador"
    assert item.x is None
    assert item.y is None


def test_map_feature_keys_normalize_world_and_regional_maps() -> None:
    assert _feature_key_for_region("United States", map_key="world") == "United States of America"
    assert _feature_key_for_region("Alabama", map_key="us") == "Alabama"


def test_map_item_preserves_regional_style_candidate_without_genre_id() -> None:
    item = _map_item_from_variant(
        RegionVariantOut(
            region_key="region-australia",
            region_name="Australia",
            region_id="region-australia",
            region_kind="country",
            genre_id=None,
            base_genre_id="wg-hip-hop",
            candidate_id=12,
            wikipedia_title="Australian Hip-Hop",
            display_title="Australian Hip-Hop",
            match_type="regional_style_candidate",
        ),
        map_key="world",
    )

    assert item.genre_id is None
    assert item.base_genre_id == "wg-hip-hop"
    assert item.candidate_id == 12
    assert item.role == "regional_style_candidate"
    assert item.selectable


def test_region_parent_relations_include_subclass_edges() -> None:
    assert "subclass_of" in REGION_PARENT_RELATIONS


def test_map_selectable_dedupe_preserves_represented_regional_children() -> None:
    visible = MapRegionItemOut(
        region_id="region-vietnam",
        region_key="vn",
        region_name="Vietnam",
        region_kind="country",
        map_key="world",
        feature_key="Vietnam",
        feature_name="Vietnam",
        genre_id="wg-v-pop",
        wikipedia_title="V-pop",
        display_title="V-pop",
        monthly_views_p30=100,
        match_type="regional_graph",
        selection_priority=0,
    )
    duplicate = MapRegionItemOut(
        region_id="region-vietnam",
        region_key="vn",
        region_name="Vietnam",
        region_kind="country",
        map_key="world",
        feature_key="Vietnam",
        feature_name="Vietnam",
        genre_id="wg-popular-music-vietnam",
        wikipedia_title="Popular music of Vietnam",
        display_title="Popular music of Vietnam",
        monthly_views_p30=10,
        match_type="regional_graph",
        selection_priority=0,
    )

    [item] = _dedupe_map_selectables([visible, duplicate])

    assert item.genre_id == "wg-v-pop"
    assert "wg-popular-music-vietnam" in item.represented_genre_ids
    assert "Popular music of Vietnam" in item.represented_titles


def test_non_country_region_match_ignores_mismatched_promoted_title() -> None:
    item = _map_item_from_region_row(
        {
            "region_id": "region-latin-america",
            "canonical_name": "Latin America",
            "region_kind": "cultural_region",
            "genre_id": "wg-q427183",
            "wikipedia_title": "Music of Puerto Rico",
            "monthly_views_p30": 115,
            "similarity_color": "#c36b51",
            "color_confidence": 0.72,
        },
        map_key="world",
        match_type="pure_region_match",
        role="cultural_region",
    )

    assert item.genre_id is None
    assert item.wikipedia_title is None
    assert item.display_title == "Latin America"
    assert item.selectable_for == "Latin America"
    assert item.represented_titles == ["Latin America"]


def test_regional_child_row_rejects_mismatched_music_of_page() -> None:
    item = _variant_from_regional_child_row(
        {
            "id": "wg-q427183",
            "region_title": "Music of Latin America",
            "region_id": "region-latin-america",
            "region_kind": "cultural_region",
            "wikipedia_title": "Music of Puerto Rico",
            "monthly_views_p30": 115,
            "similarity_color": "#c36b51",
            "color_confidence": 0.72,
        },
        match_type="regional_graph",
    )

    assert item is None


def test_regional_child_row_rejects_mismatched_demonym_variant() -> None:
    item = _variant_from_regional_child_row(
        {
            "id": "wg-q2631396",
            "region_title": "Music of Latin America",
            "region_id": "region-latin-america",
            "region_kind": "cultural_region",
            "wikipedia_title": "Brazilian rock",
            "monthly_views_p30": 48,
            "similarity_color": "#b35a51",
            "color_confidence": 0.77,
        },
        match_type="regional_graph",
    )

    assert item is None
