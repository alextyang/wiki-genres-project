"""Tests for manual curation rules."""

from wiki_genres.curation import (
    MANUAL_DISPLAY_EDGES,
    MANUAL_HIGH_LEVEL_ROOT_TITLES,
    MANUAL_MUSIC_OF_COUNTRY_TITLES,
    MANUAL_NON_GENRE_TITLES,
)


def test_manual_high_level_roots_do_not_mount_under_world_music() -> None:
    assert MANUAL_HIGH_LEVEL_ROOT_TITLES == ("Religious music", "Latin music")


def test_manual_non_genre_titles_disable_broad_non_genre_pages() -> None:
    assert "Popular music" in MANUAL_NON_GENRE_TITLES


def test_manual_display_edges_use_music_of_regional_mounts() -> None:
    pairs = {(edge.parent_title, edge.child_title) for edge in MANUAL_DISPLAY_EDGES}

    assert ("Soundtrack", "Film score") in pairs
    assert ("Soundtrack", "Theme music") in pairs
    assert ("Soundtrack", "Theatre music") in pairs
    assert ("Folk music", "Work song") in pairs
    assert ("Pop music", "Italian popular music") in pairs
    assert ("Electronic dance music", "Bass music") in pairs
    assert ("Hip-hop", "Hipdut") in pairs
    assert ("Music of Indonesia", "Gamelan") in pairs
    assert ("Music of the United States", "Indigenous music of North America") in pairs
    assert ("Music of Canada", "Indigenous music of North America") in pairs
    assert ("Music of Mexico", "Indigenous music of North America") in pairs
    assert ("World music", "Tango") not in pairs
    assert ("Music", "Tango") not in pairs


def test_country_music_pages_promoted_from_strict_filter_gaps() -> None:
    assert "Music of Kuwait" in MANUAL_MUSIC_OF_COUNTRY_TITLES
    assert "Music of Trinidad and Tobago" in MANUAL_MUSIC_OF_COUNTRY_TITLES
    assert "Music of Wales" in MANUAL_MUSIC_OF_COUNTRY_TITLES
    assert "Music of Western Sahara" in MANUAL_MUSIC_OF_COUNTRY_TITLES
