"""Tests for region review staging helpers."""

from wiki_genres.loader.region_review import normalize_region_label, stable_key


def test_normalize_region_label_removes_music_region_noise() -> None:
    assert normalize_region_label("Music of the Caribbean") == "caribbean"
    assert normalize_region_label("Regional music genres of Latin America") == "latin america"
    assert normalize_region_label("Music of Georgia (country)") == "georgia"


def test_region_review_stable_key_is_repeatable() -> None:
    assert stable_key("region", "a", "b") == stable_key("region", "a", "b")
    assert stable_key("region", "a", "b") != stable_key("region", "b", "a")
