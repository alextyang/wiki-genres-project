"""Playlist visibility rules for public API responses."""

from __future__ import annotations

from pathlib import Path

import pytest

import wiki_genres.api.routes.genres as genres_route


def test_playable_playlist_track_condition_filters_unplayable_rows() -> None:
    assert (
        genres_route._playable_playlist_track_condition("tracks")
        == "tracks.is_embeddable IS DISTINCT FROM false"
    )
    assert (
        genres_route._playable_playlist_track_condition()
        == "is_embeddable IS DISTINCT FROM false"
    )


@pytest.mark.asyncio
async def test_playlist_endpoint_query_excludes_unplayable_rows(monkeypatch) -> None:
    class FakeResult:
        def __init__(self, *, row=None, rows=None):
            self.row = row
            self.rows = rows or []

        def mappings(self):
            return self

        def fetchone(self):
            return self.row

        def __iter__(self):
            return iter(self.rows)

    class FakeSession:
        def __init__(self):
            self.queries: list[str] = []

        async def execute(self, statement, params=None):
            self.queries.append(str(statement))
            if len(self.queries) == 1:
                return FakeResult(row={"id": "wg-test", "wikipedia_title": "Test genre"})
            return FakeResult(rows=[])

    class FakeSessionScope:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    session = FakeSession()
    monkeypatch.setattr(genres_route, "session_scope", lambda: FakeSessionScope(session))

    result = await genres_route.get_genre_playlist("wg-test")

    assert result.tracks == []
    assert len(session.queries) == 2
    assert "tracks.is_embeddable IS DISTINCT FROM false" in session.queries[1]


def test_genre_detail_and_catalog_queries_exclude_unplayable_rows() -> None:
    source = Path(genres_route.__file__).read_text(encoding="utf-8")

    assert source.count('_playable_playlist_track_condition("tracks")') >= 2
    assert "WHERE is_embeddable IS DISTINCT FROM false" in source
