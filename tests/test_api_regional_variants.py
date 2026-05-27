"""Tests for regional-variant response shaping."""

import pytest

import wiki_genres.api.routes.genres as genres_route
from wiki_genres.api.routes.genres import (
    MAP_VARIANT_EVIDENCE_RELATIONS,
    MAP_VARIANT_RELATIONS,
    REGION_PARENT_RELATIONS,
    REGIONAL_SCENE_EVIDENCE_RELATION,
    REGIONAL_SCENE_RELATION,
    _dedupe_map_selectables,
    _feature_key_for_region,
    _map_item_from_variant,
    _map_item_from_region_row,
    _most_specific_regional_graph_rows,
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


def test_map_variant_relations_are_production_display_only() -> None:
    assert set(MAP_VARIANT_RELATIONS) == {"subgenre", "derivative", "fusion_genre"}
    assert set(MAP_VARIANT_EVIDENCE_RELATIONS) == {"subgenre", "derivative", "fusion_genre"}
    assert REGIONAL_SCENE_RELATION not in MAP_VARIANT_RELATIONS
    assert REGIONAL_SCENE_EVIDENCE_RELATION not in MAP_VARIANT_EVIDENCE_RELATIONS


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


def test_regional_graph_rows_keep_most_specific_region_links() -> None:
    rows = [
        {"id": "cape-jazz", "region_kind": "continent", "region_title": "Music of Africa"},
        {
            "id": "cape-jazz",
            "region_kind": "country",
            "region_title": "Music of South Africa",
        },
        {"id": "reggae", "region_kind": "country", "region_title": "Music of Jamaica"},
        {"id": "reggae", "region_kind": "country", "region_title": "Music of Guyana"},
        {
            "id": "chamber-jazz",
            "region_kind": "cultural_region",
            "region_title": "Music of Latin America",
        },
    ]

    filtered = _most_specific_regional_graph_rows(rows)

    assert [row["region_title"] for row in filtered] == [
        "Music of South Africa",
        "Music of Jamaica",
        "Music of Guyana",
        "Music of Latin America",
    ]


@pytest.mark.asyncio
async def test_projected_superregion_countries_use_selected_variant_color(monkeypatch) -> None:
    source = MapRegionItemOut(
        region_id="region-north-africa",
        region_key="region-north-africa",
        region_name="North Africa",
        region_kind="subregion",
        map_key="world",
        feature_key="North Africa",
        feature_name="North Africa",
        genre_id="wg-north-africa",
        wikipedia_title="Music of North Africa",
        display_title="Music of North Africa",
        monthly_views_p30=90,
        similarity_color="#123456",
        color_confidence=0.9,
        match_type="regional_graph",
    )

    async def fake_descendants(session, region_ids):
        assert region_ids == ["region-north-africa"]
        return [
            {
                "seed_region_id": "region-north-africa",
                "country_region_id": "region-morocco",
                "country_name": "Morocco",
                "monthly_views_p30": 10,
                "similarity_color": "#abcdef",
                "color_confidence": 0.4,
            }
        ]

    monkeypatch.setattr(
        genres_route,
        "_pure_region_descendant_country_rows",
        fake_descendants,
    )
    async def empty_rows(*args, **kwargs):
        return []

    monkeypatch.setattr(genres_route, "_pure_region_country_ancestor_rows", empty_rows)
    monkeypatch.setattr(genres_route, "_pure_region_group_ancestor_rows", empty_rows)
    monkeypatch.setattr(genres_route, "_region_country_ancestor_rows", empty_rows)
    monkeypatch.setattr(genres_route, "_region_group_ancestor_rows", empty_rows)

    expanded = await genres_route._expand_map_items_with_pure_region_graph(
        object(), [source], map_key="world"
    )
    projected = next(item for item in expanded if item.region_name == "Morocco")

    assert projected.display_title == "Music of North Africa"
    assert projected.monthly_views_p30 == 90
    assert projected.similarity_color == "#123456"
    assert projected.color_confidence == 0.9


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


@pytest.mark.asyncio
async def test_submap_context_opens_for_exact_special_region(monkeypatch) -> None:
    expected_items = [object()]

    async def fake_region_child_map_items(session, *, parent_region_id: str, map_key: str):
        assert parent_region_id == "region-united-states"
        assert map_key == "us"
        return expected_items

    monkeypatch.setattr(
        genres_route, "_region_child_map_items", fake_region_child_map_items
    )

    active_map, items = await genres_route._us_context_for_region(
        object(), {"region_id": "region-united-states"}
    )

    assert active_map == "us"
    assert items == expected_items


@pytest.mark.asyncio
async def test_submap_context_does_not_open_for_child_region() -> None:
    class ExplodingSession:
        async def scalar(self, *args, **kwargs):
            raise AssertionError("child-region submap detection should not query parents")

    active_map, items = await genres_route._us_context_for_region(
        ExplodingSession(), {"region_id": "region-texas"}
    )

    assert active_map == "world"
    assert items == []
