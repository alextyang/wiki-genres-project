"""Tests for Phase 4 regional relationship review rules."""

from wiki_genres.loader.region_validation import (
    RegionContainmentEdge,
    find_containment_cycles,
    review_region_genre_relationship,
    review_region_relationship,
)


def test_review_accepts_category_admin_parent() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Montserrat",
            "parent_name": "Caribbean",
            "relation": "admin_parent",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music of the Caribbean by dependent territory",
        }
    )

    assert decision.status == "accepted"


def test_review_accepts_music_in_category_admin_parent() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Koblenz",
            "parent_name": "Rhineland-Palatinate",
            "relation": "admin_parent",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music in Rhineland-Palatinate",
        }
    )

    assert decision.status == "accepted"


def test_review_flags_container_region() -> None:
    decision = review_region_relationship(
        {
            "child_name": "By country",
            "parent_name": "Latin America",
            "relation": "cultural_region_of",
            "source_type": "wikipedia_list",
            "source_title": "List of cultural and regional genres of music",
        }
    )

    assert decision.status == "needs_review"


def test_review_accepts_sectioned_list_region_genre() -> None:
    decision = review_region_genre_relationship(
        {
            "region_name": "Montserrat",
            "genre_title": "Calypso music",
            "relation": "regional_scene",
            "source_type": "wikipedia_list",
            "source_title": "List of Caribbean music genres",
            "source_section": "Montserrat",
        }
    )

    assert decision.status == "accepted"


def test_review_accepts_list_row_context_region_hierarchy() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Aegean Islands",
            "parent_name": "Greece",
            "relation": "part_of",
            "source_type": "wikipedia_list",
            "source_title": "List of cultural and regional genres of music",
            "raw_payload": {"list_context_region": "Greece"},
        }
    )

    assert decision.status == "accepted"


def test_review_accepts_nested_list_row_context_region_hierarchy() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Adelaide",
            "parent_name": "Australia",
            "relation": "part_of",
            "source_type": "wikipedia_list",
            "source_title": "List of cultural and regional genres of music",
            "raw_payload": {"review": {"list_context_region": "Australia"}},
        }
    )

    assert decision.status == "accepted"


def test_review_accepts_manual_regional_parent_alias() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Albanian",
            "parent_name": "Albania",
            "relation": "part_of",
            "source_type": "manual",
            "source_title": "regional parent alias",
            "raw_payload": {"relation_source": "regional_parent_alias"},
        }
    )

    assert decision.status == "accepted"


def test_review_accepts_latin_american_cultural_category() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Argentine",
            "parent_name": "Latin America",
            "relation": "cultural_region_of",
            "source_type": "wikipedia_category",
            "source_title": "Category:Latin American styles of music",
            "raw_payload": {},
        }
    )

    assert decision.status == "accepted"


def test_review_rejects_inverse_nordic_country_cultural_edge() -> None:
    decision = review_region_relationship(
        {
            "child_name": "Nordic",
            "parent_name": "Denmark",
            "relation": "cultural_region_of",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music of Denmark",
            "raw_payload": {},
        }
    )

    assert decision.status == "rejected"


def test_review_rejects_artifact_region_genre_target() -> None:
    decision = review_region_genre_relationship(
        {
            "region_name": "Caribbean",
            "genre_title": "List of Caribbean music genres",
            "relation": "regional_scene",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music of the Caribbean",
            "source_section": None,
        }
    )

    assert decision.status == "rejected"


def test_find_containment_cycles_reports_named_cycle() -> None:
    cycles = find_containment_cycles(
        [
            RegionContainmentEdge("a", "A", "b", "B", "part_of"),
            RegionContainmentEdge("b", "B", "c", "C", "part_of"),
            RegionContainmentEdge("c", "C", "a", "A", "part_of"),
        ]
    )

    assert cycles == [["A", "B", "C", "A"]]
