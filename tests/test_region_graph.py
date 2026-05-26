"""Tests for regional graph seed helpers."""

from wiki_genres.loader.region_graph import (
    build_music_region_page,
    candidate_region_name_for_row,
    clean_region_name,
    normalize_region_id,
    parent_region_name_for_candidate,
    relation_for_region_edge,
    region_name_from_music_title,
    source_region_name,
)


def test_region_name_from_music_title_handles_articles_and_disambiguation() -> None:
    assert region_name_from_music_title("Music of the Bahamas") == "Bahamas"
    assert region_name_from_music_title("Music of Georgia (country)") == "Georgia"
    assert region_name_from_music_title("Rock music") is None


def test_normalize_region_id_is_stable_ascii_slug() -> None:
    assert normalize_region_id("São Tomé and Príncipe") == "region-sao-tome-and-principe"


def test_build_music_region_page_maps_genre_to_region() -> None:
    page = build_music_region_page(
        {
            "id": "wg-q6942068",
            "wikipedia_title": "Music of Ecuador",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Music_of_Ecuador",
        }
    )

    assert page is not None
    assert page.genre_id == "wg-q6942068"
    assert page.region_id == "region-ecuador"
    assert page.region_name == "Ecuador"


def test_source_region_name_ignores_list_grouping_sections() -> None:
    assert source_region_name("List of Caribbean music genres", "Colombia") == "Colombia"
    assert source_region_name("List of cultural and regional genres of music", "By country") is None
    assert source_region_name("List of music genres and styles", "Classical") is None
    assert source_region_name("List of music genres and styles", "African") == "Africa"
    assert (
        source_region_name(
            "List of cultural and regional genres of music",
            "International ethnic groups",
        )
        is None
    )


def test_clean_region_name_removes_container_suffixes() -> None:
    assert clean_region_name("Spain by autonomous community") == "Spain"
    assert clean_region_name("Canada by populated place") == "Canada"
    assert clean_region_name("dependent territories of the United Kingdom") == "United Kingdom"
    assert clean_region_name("Latin American") == "Latin America"
    assert clean_region_name("American") == "United States"
    assert clean_region_name("North American") == "North America"


def test_relation_for_region_edge_does_not_match_latin_inside_palatinate() -> None:
    assert (
        relation_for_region_edge("music_region_category", "Category:Music in Rhineland-Palatinate")
        == "admin_parent"
    )
    assert (
        relation_for_region_edge("cultural_region_page", "Category:Music of Latin America")
        == "cultural_region_of"
    )


def test_parent_region_name_for_list_candidate_requires_semantic_context() -> None:
    assert (
        parent_region_name_for_candidate(
            {
                "source_type": "wikipedia_list",
                "source_title": "List of Caribbean music genres",
                "source_section": "Benna",
                "raw_payload": {
                    "list_section": "Benna",
                    "list_context_region": None,
                },
            }
        )
        is None
    )
    assert parent_region_name_for_candidate(
        {
            "source_type": "wikipedia_list",
            "source_title": "List of Caribbean music genres",
            "source_section": "Jamaica",
            "raw_payload": {
                "list_section": "Jamaica",
                "list_context_region": "Jamaica",
            },
        }
    ) == "Jamaica"


def test_parent_region_name_maps_style_demonyms_to_region_parent() -> None:
    row = {
        "candidate_type": "regional_genre_page",
        "title": "Category:Albanian styles of music",
        "suggested_region_name": None,
        "source_type": "wikipedia_category",
        "source_title": "Category:Music of Albania",
        "source_section": None,
        "raw_payload": {},
    }
    assert candidate_region_name_for_row(row) == "Albanian"
    assert parent_region_name_for_candidate(row) == "Albania"


def test_parent_region_name_maps_explicit_region_alias_to_region_parent() -> None:
    assert parent_region_name_for_candidate(
        {
            "candidate_type": "music_region_page",
            "title": "Music in Tunis",
            "suggested_region_name": "Tunis",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music by city",
            "source_section": None,
            "raw_payload": {},
        }
    ) == "Tunisia"


def test_parent_region_name_maps_source_style_alias_before_self_edge() -> None:
    assert parent_region_name_for_candidate(
        {
            "candidate_type": "music_region_page",
            "title": "Music of Spain",
            "suggested_region_name": "Spain",
            "source_type": "wikipedia_category",
            "source_title": "Category:Spanish folk music",
            "source_section": None,
            "raw_payload": {},
        }
    ) == "Spain"
