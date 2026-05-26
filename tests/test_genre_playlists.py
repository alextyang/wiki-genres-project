"""Tests for manually curated genre playlists."""

from __future__ import annotations

import pytest

from wiki_genres.loader.genre_playlists import _read_playlist_csv, validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://music.youtube.com/watch?v=abc123",
        "https://music.youtube.com/playlist?list=PLabc123",
        "https://youtube.com/embed/abc123",
        "https://youtu.be/abc123",
    ],
)
def test_validate_youtube_url_accepts_youtube_hosts(url: str) -> None:
    assert validate_youtube_url(f" {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=abc123",
        "ftp://youtube.com/watch?v=abc123",
        "https://youtube.com",
    ],
)
def test_validate_youtube_url_rejects_non_public_youtube_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_youtube_url(url)


def test_playlist_csv_allows_blank_artist(tmp_path) -> None:
    csv_path = tmp_path / "playlist.csv"
    csv_path.write_text(
        "\n".join(
            [
                "genre_id,song_title,artist,youtube_url,ordinal",
                "wg-q188450,Example Song,,https://www.youtube.com/watch?v=abc123,0",
            ]
        ),
        encoding="utf-8",
    )

    rows = _read_playlist_csv(csv_path)

    assert len(rows) == 1
    assert rows[0].artist == ""
