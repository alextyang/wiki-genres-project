"""Tests for merge-review staging helpers."""

from wiki_genres.loader.merge_review import normalize_label, stable_key


def test_normalize_label_removes_music_suffixes_and_punctuation() -> None:
    assert normalize_label("Hip-hop music") == "hip hop"
    assert normalize_label("Bachata (music)") == "bachata"
    assert normalize_label("Music genre styles") == ""


def test_stable_key_is_repeatable() -> None:
    assert stable_key("merge", "a", "b") == stable_key("merge", "a", "b")
    assert stable_key("merge", "a", "b") != stable_key("merge", "b", "a")
