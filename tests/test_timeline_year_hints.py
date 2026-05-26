from wiki_genres.loader.timeline_year_hints import (
    extract_year_hints,
    is_regional_music_page_title,
)


def test_origin_hint_uses_first_temporal_phrase() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Soukous",
        summary=None,
        origins=["1966 in the Republic of the Congo; the 1980s in France."],
        categories=[],
    )

    assert hints[0].year_start == 1966
    assert hints[0].year_end is None
    assert hints[0].estimated_start == 1966
    assert hints[0].estimated_end == 1966
    assert hints[0].year_observation_count == 2
    assert hints[0].beginning_start == 1966
    assert hints[0].beginning_end == 1966
    assert hints[0].beginning_observation_count == 1
    assert hints[0].relevance_start == 1966
    assert hints[0].relevance_end == 1989
    assert hints[0].relevance_observation_count == 2
    assert hints[0].confidence == "high"


def test_origin_hint_keeps_first_decade_before_later_range() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Noise music",
        summary=None,
        origins=["1910s, Italy; 1960s – late 1970s, United States, Japan and Europe"],
        categories=[],
    )

    assert hints[0].year_start == 1910
    assert hints[0].year_end == 1919
    assert hints[0].estimated_start == 1910
    assert hints[0].estimated_end == 1919
    assert hints[0].relevance_start == 1910
    assert hints[0].relevance_end == 1979


def test_summary_origin_sentence_hint() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Crunk",
        summary=(
            "Crunk is a subgenre of hip hop music that emerged in the early 1990s "
            "and gained mainstream success during the mid 2000s."
        ),
        origins=[],
        categories=[],
    )

    assert hints[0].source_type == "summary_sentence"
    assert hints[0].confidence == "medium"
    assert hints[0].year_start == 1990
    assert hints[0].year_end == 1993
    assert hints[0].estimated_start == 1990
    assert hints[0].estimated_end == 1993
    assert hints[0].relevance_start == 1990
    assert hints[0].relevance_end == 2006


def test_summary_term_origin_is_not_genre_origin() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Folk music",
        summary=(
            "The term originated in the 19th century, but folk music extends "
            "beyond that."
        ),
        origins=[],
        categories=[],
    )

    assert hints == []


def test_later_origin_cue_is_not_pulled_to_earlier_inspiration() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Jerk",
        summary=(
            "Jerk is an Internet microgenre of hip-hop that emerged in New York "
            "City during the early 2020s, drawing inspiration from the original "
            "wave of jerk rap, known as jerkin' in street dance culture, which "
            "initially gained popularity in the late 2000s and early 2010s."
        ),
        origins=[],
        categories=[],
    )

    assert hints[0].year_start == 2020
    assert hints[0].estimated_start == 2020
    assert hints[0].beginning_end == 2023
    assert hints[0].relevance_start == 2020
    assert hints[0].relevance_end is None


def test_category_hint_is_low_confidence() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Electronic dance music",
        summary=None,
        origins=[],
        categories=["Category:1980s in music"],
    )

    assert hints[0].source_type == "category"
    assert hints[0].confidence == "low"
    assert hints[0].year_start == 1980
    assert hints[0].year_end == 1989
    assert hints[0].beginning_start == 1980
    assert hints[0].beginning_end == 1989
    assert hints[0].relevance_start == 1980
    assert hints[0].relevance_end == 1989


def test_category_genre_centuries_do_not_become_relevance_lifespan() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="A cappella",
        summary=None,
        origins=[],
        categories=[
            "Category:16th-century music genres",
            "Category:20th-century music genres",
            "Category:21st-century music genres",
        ],
    )

    assert hints[0].year_start == 1500
    assert hints[0].beginning_start == 1500
    assert hints[0].beginning_end == 1599
    assert hints[0].relevance_start == 1500
    assert hints[0].relevance_end == 1599


def test_category_fallback_prefers_decades_over_broad_century() -> None:
    hints = extract_year_hints(
        genre_id="wg-test",
        title="Thrash metal",
        summary="Thrash metal is an extreme subgenre of heavy metal music.",
        origins=[],
        categories=[
            "Category:20th-century music genres",
            "Category:1980s in music",
            "Category:1990s in music",
            "Category:2000s in music",
        ],
    )

    assert hints[0].source_type == "category"
    assert hints[0].confidence == "low"
    assert hints[0].year_start == 1980
    assert hints[0].beginning_start == 1980
    assert hints[0].beginning_end == 1989
    assert hints[0].relevance_start == 1980
    assert hints[0].relevance_end == 2009


def test_regional_music_pages_are_timeline_excluded() -> None:
    assert is_regional_music_page_title("Music of Latin America")
    assert is_regional_music_page_title("The music of Austria")
    assert not is_regional_music_page_title("Electronic music")
