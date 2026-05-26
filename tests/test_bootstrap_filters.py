"""Tests for bootstrap crawl eligibility filters."""

from __future__ import annotations

from wiki_genres.crawler.bootstrap import _is_music_genre_candidate
from wiki_genres.parser.types import ParsedEdge, ParsedGenre, ParsedWikidataEntity


def _parsed(has_infobox: bool = False, categories: list[str] | None = None) -> ParsedGenre:
    return ParsedGenre(
        wikipedia_title="Example",
        wikipedia_url="https://en.wikipedia.org/wiki/Example",
        wikidata_qid="Q1",
        has_infobox=has_infobox,
        summary=None,
        infobox_color=None,
        upstream_revision=None,
        raw_wikitext_sha256="sha",
        categories=categories or [],
    )


def test_music_infobox_pages_are_genre_candidates() -> None:
    assert _is_music_genre_candidate(_parsed(has_infobox=True), None)


def test_wikidata_music_genre_class_keeps_no_infobox_page() -> None:
    wikidata = ParsedWikidataEntity(
        qid="Q851213",
        edges=[
            ParsedEdge(
                relation="instance_of",
                raw_label="Q188451",
                wiki_target=None,
                source="wikidata",
            )
        ],
    )

    assert _is_music_genre_candidate(_parsed(), wikidata)


def test_country_page_without_music_evidence_is_not_candidate() -> None:
    wikidata = ParsedWikidataEntity(
        qid="Q30",
        edges=[
            ParsedEdge(
                relation="instance_of",
                raw_label="Q6256",
                wiki_target=None,
                source="wikidata",
            )
        ],
    )

    assert not _is_music_genre_candidate(_parsed(categories=["Category:Countries"]), wikidata)


def test_manual_no_infobox_review_titles_are_genre_candidates() -> None:
    parsed = _parsed()
    parsed.wikipedia_title = "Vocal jazz"

    assert _is_music_genre_candidate(parsed, None)


def test_manual_music_of_country_titles_are_genre_candidates() -> None:
    parsed = _parsed()
    parsed.wikipedia_title = "Music of Barbados"

    assert _is_music_genre_candidate(parsed, None)
