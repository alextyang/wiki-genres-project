"""Tests for Phase 2 regional candidate discovery helpers."""

from wiki_genres.loader.region_discovery import (
    SOURCE_LIST,
    DiscoverySource,
    auto_review_candidate_payload,
    candidate_from_title,
    category_source_from_member,
    classify_candidate_title,
    extract_list_candidates,
    normalize_title,
    review_payload_from_candidate_row,
)


def test_classifies_music_region_pages_and_categories() -> None:
    assert classify_candidate_title("Music of Montserrat") == (
        "music_region_page",
        "discovered",
        0.88,
    )
    assert classify_candidate_title("Category:Music of the Caribbean by country", namespace=14)[
        0
    ] == "music_region_category"
    assert classify_candidate_title("List of Caribbean music genres")[0] == "regional_music_list"
    assert classify_candidate_title("Category:Caribbean musicians", namespace=14)[1] == "rejected"
    assert classify_candidate_title("Category:Music festivals in the Caribbean", namespace=14)[
        1
    ] == "rejected"
    assert classify_candidate_title("Category:American Celtic music groups", namespace=14)[
        1
    ] == "rejected"
    assert classify_candidate_title("Category:2018 in Finnish music", namespace=14)[1] == "rejected"
    assert classify_candidate_title("Category:Music journalism in France", namespace=14)[
        1
    ] == "rejected"
    assert classify_candidate_title("Category:Music history of France", namespace=14)[
        1
    ] == "needs_gpt_review"
    assert classify_candidate_title("Category:Classical music in London", namespace=14)[
        1
    ] == "needs_gpt_review"
    assert classify_candidate_title("Category:Music in London", namespace=14)[0] == (
        "music_region_category"
    )


def test_candidate_from_music_of_title_suggests_region() -> None:
    source = DiscoverySource("wikipedia_category", "Category:Music of the Caribbean")
    candidate = candidate_from_title("Music of Montserrat", source, namespace=0)

    assert candidate is not None
    assert candidate.candidate_type == "music_region_page"
    assert candidate.suggested_region_id == "region-montserrat"
    assert candidate.suggested_region_name == "Montserrat"


def test_candidate_from_music_in_title_suggests_region() -> None:
    source = DiscoverySource("wikipedia_category", "Category:Music of England by city")
    candidate = candidate_from_title("Category:Music in London", source, namespace=14)

    assert candidate is not None
    assert candidate.candidate_type == "music_region_category"
    assert candidate.suggested_region_id == "region-london"
    assert candidate.suggested_region_name == "London"


def test_category_source_from_regional_subcategory() -> None:
    parent = DiscoverySource("wikipedia_category", "Category:Music of the Caribbean")
    child = category_source_from_member(
        "Category:Music of the Caribbean by country",
        parent=parent,
        namespace=14,
    )

    assert child is not None
    assert child.parent_key == parent.source_key
    assert child.depth == 1


def test_extract_list_candidates_preserves_sections() -> None:
    source = DiscoverySource(SOURCE_LIST, "List of Caribbean music genres")
    candidates = extract_list_candidates(
        """
== Montserrat ==
* [[Calypso music]]
* [[Music of Montserrat]]
== Trinidad and Tobago ==
* [[Soca music]]
""",
        source,
    )

    by_title = {candidate.title: candidate for candidate in candidates}
    assert by_title["Music of Montserrat"].source_section == "Montserrat"
    assert by_title["Music of Montserrat"].suggested_region_id == "region-montserrat"
    assert by_title["Calypso music"].source_section == "Montserrat"


def test_extract_list_candidates_binds_inline_country_rows_to_genre_links() -> None:
    source = DiscoverySource(SOURCE_LIST, "List of Caribbean music genres")
    candidates = extract_list_candidates(
        """
* [[Jamaica]]: [[Reggae]], [[Dancehall]], [[Music of Jamaica]]
* [[Trinidad and Tobago]] – [[Calypso music]]; [[Soca music]]
""",
        source,
    )

    by_title = {candidate.title: candidate for candidate in candidates}
    assert by_title["Reggae"].candidate_type == "regional_genre_page"
    assert by_title["Reggae"].source_section == "Jamaica"
    assert by_title["Reggae"].raw_payload["list_context_region"] == "Jamaica"
    assert by_title["Reggae"].raw_payload["list_row_type"] == "inline_context_row"
    assert by_title["Dancehall"].source_section == "Jamaica"
    assert "Jamaica" not in by_title
    assert by_title["Music of Jamaica"].candidate_type == "music_region_page"
    assert by_title["Music of Jamaica"].source_section == "Jamaica"
    assert by_title["Calypso music"].source_section == "Trinidad and Tobago"
    assert by_title["Soca music"].source_section == "Trinidad and Tobago"


def test_extract_list_candidates_binds_definition_and_table_rows() -> None:
    source = DiscoverySource(SOURCE_LIST, "List of Caribbean music genres")
    candidates = extract_list_candidates(
        """
; [[Montserrat]]: [[Calypso music]], [[Cadence-lypso]]
{| class="wikitable"
! Country !! Genres
|-
| [[Barbados]] || [[Spouge]] || [[Tuk band]]
|}
""",
        source,
    )

    by_title = {candidate.title: candidate for candidate in candidates}
    assert by_title["Calypso music"].source_section == "Montserrat"
    assert by_title["Cadence-lypso"].source_section == "Montserrat"
    assert by_title["Spouge"].source_section == "Barbados"
    assert by_title["Spouge"].raw_payload["list_row_type"] == "table_row"
    assert by_title["Tuk band"].source_section == "Barbados"
    assert "Barbados" not in by_title


def test_extract_list_candidates_inherits_nested_bullet_region_context() -> None:
    source = DiscoverySource(SOURCE_LIST, "List of Caribbean music genres")
    candidates = extract_list_candidates(
        """
* Jamaica
** [[Reggae]]
** [[Dancehall]]
* [[Music of Trinidad and Tobago]]
** [[Calypso music]]
""",
        source,
    )

    by_title = {candidate.title: candidate for candidate in candidates}
    assert by_title["Reggae"].source_section == "Jamaica"
    assert by_title["Dancehall"].source_section == "Jamaica"
    assert by_title["Calypso music"].source_section == "Trinidad and Tobago"


def test_extract_list_candidates_filters_live_contexts_to_known_regions() -> None:
    source = DiscoverySource(SOURCE_LIST, "List of Caribbean music genres")
    candidates = extract_list_candidates(
        """
* [[Benna]]
** [[Extempo]]
** [[Soca music]]
* [[Bahamas]]
** [[Goombay]]
** [[Junkanoo]]
""",
        source,
        known_region_names={"bahamas"},
    )

    by_title = {candidate.title: candidate for candidate in candidates}
    assert "Extempo" not in by_title
    assert by_title["Soca music"].source_section is None
    assert by_title["Goombay"].source_section == "Bahamas"
    assert by_title["Junkanoo"].source_section == "Bahamas"


def test_normalize_title_strips_noise() -> None:
    assert normalize_title(":Music_of_Montserrat") == "Music of Montserrat"


def test_auto_review_rejects_regional_source_non_genre_artifacts() -> None:
    base_row = {
        "candidate_type": "regional_genre_page",
        "suggested_region_name": None,
        "source_title": "Category:Norwegian folk music",
        "confidence": 0.5,
    }

    assert (
        auto_review_candidate_payload(
            {**base_row, "title": "Norwegian Folk Music Research Association"}
        ).decision
        == "reject"
    )
    assert auto_review_candidate_payload({**base_row, "title": "Musical Atlas"}).decision == (
        "reject"
    )
    assert (
        auto_review_candidate_payload({**base_row, "title": "Old Town School of Folk Music"}).decision
        == "reject"
    )


def test_review_payload_preserves_source_lineage() -> None:
    payload = review_payload_from_candidate_row(
        {
            "candidate_key": "candidate-1",
            "candidate_type": "music_region_category",
            "normalized_title": "category:music in london",
            "title": "Category:Music in London",
            "suggested_region_name": "London",
            "source_key": "source-1",
            "source_type": "wikipedia_category",
            "source_title": "Category:Music of England by city",
            "source_url": "https://en.wikipedia.org/wiki/Category:Music_of_England_by_city",
            "source_section": None,
            "source_depth": 3,
            "evidence_text": "Category:Music in London is a member of Category:Music of England by city.",
            "confidence": 0.76,
        }
    )

    assert payload["evidence"]["source_key"] == "source-1"
    assert payload["evidence"]["source_depth"] == 3
    assert payload["evidence"]["evidence_kind"] == "category_membership"
    assert payload["suggested_region_kind"] == "unknown"
