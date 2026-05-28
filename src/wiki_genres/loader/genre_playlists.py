"""Manual YouTube playlist storage for genre pages."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from wiki_genres.db import session_scope
from wiki_genres.db_migrations import apply_migrations

PLAYLIST_CSV_FIELDS = ("genre_id", "song_title", "artist", "youtube_url", "ordinal")
DEFAULT_PLAYLIST_DISCOVERY_GROUP = "manual"
REMOVED_LEGACY_PLAYLIST_TABLE_MESSAGE = (
    "The legacy flat playlist table was removed after archiving to the warehouse. "
    "Import approved playlists through the normalized playlist warehouse pipeline."
)


@dataclass(frozen=True)
class PlaylistTrack:
    genre_id: str
    ordinal: int
    song_title: str
    artist: str
    youtube_url: str
    playlist_discovery_group: str = DEFAULT_PLAYLIST_DISCOVERY_GROUP


@dataclass(frozen=True)
class PlaylistImportStats:
    rows_read: int
    rows_written: int
    genres_touched: int


def validate_youtube_url(url: str) -> str:
    """Return a trimmed YouTube URL or raise ValueError."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("YouTube URL must start with http:// or https://")
    if host.startswith("www."):
        host = host[4:]
    if host not in {"youtube.com", "music.youtube.com", "youtu.be"}:
        raise ValueError("YouTube URL must be from youtube.com, music.youtube.com, or youtu.be")
    if not parsed.path or parsed.path == "/":
        raise ValueError("YouTube URL must include a video or playlist path")
    return cleaned


async def add_playlist_track(
    *,
    genre_id: str,
    song_title: str,
    artist: str,
    youtube_url: str,
    ordinal: int | None = None,
    playlist_discovery_group: str = DEFAULT_PLAYLIST_DISCOVERY_GROUP,
) -> PlaylistTrack:
    """Add or replace one curated playlist track for a genre."""
    raise RuntimeError(REMOVED_LEGACY_PLAYLIST_TABLE_MESSAGE)


async def list_playlist_tracks(genre_id: str) -> list[PlaylistTrack]:
    """Return the curated YouTube playlist for a genre."""
    await apply_migrations()
    async with session_scope() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT genre_id, ordinal, song_title, artist, youtube_url
                    FROM wg_genre_approved_client_playlist_tracks
                    WHERE genre_id = :genre_id
                    ORDER BY ordinal, artist, song_title
                """),
                {"genre_id": genre_id},
            )
        ).mappings()

        return [
            PlaylistTrack(
                genre_id=str(row["genre_id"]),
                ordinal=int(row["ordinal"]),
                song_title=str(row["song_title"]),
                artist=str(row["artist"]),
                youtube_url=str(row["youtube_url"]),
                playlist_discovery_group="approved",
            )
            for row in rows
        ]


async def import_playlist_csv(path: Path, *, replace_genres: bool = False) -> PlaylistImportStats:
    """Import curated playlist rows from a local CSV file."""
    raise RuntimeError(REMOVED_LEGACY_PLAYLIST_TABLE_MESSAGE)


def _read_playlist_csv(path: Path) -> list[PlaylistTrack]:
    rows: list[PlaylistTrack] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing_fields = [
            field for field in PLAYLIST_CSV_FIELDS if field not in (reader.fieldnames or [])
        ]
        if missing_fields:
            raise ValueError(f"CSV missing required column(s): {', '.join(missing_fields)}")

        next_ordinal_by_genre: dict[str, int] = {}
        for index, row in enumerate(reader, start=2):
            genre_id = _require_text(row.get("genre_id", ""), f"genre_id on line {index}")
            title = _require_text(row.get("song_title", ""), f"song_title on line {index}")
            artist = _optional_text(row.get("artist", ""))
            youtube_url = validate_youtube_url(row.get("youtube_url", ""))
            playlist_discovery_group = (
                _optional_text(row.get("playlist_discovery_group", ""))
                or _optional_text(row.get("discovery_version", ""))
                or DEFAULT_PLAYLIST_DISCOVERY_GROUP
            )
            ordinal_text = (row.get("ordinal") or "").strip()
            if ordinal_text:
                try:
                    ordinal = int(ordinal_text)
                except ValueError as exc:
                    raise ValueError(f"ordinal on line {index} must be an integer") from exc
                if ordinal < 0:
                    raise ValueError(f"ordinal on line {index} must be non-negative")
            else:
                ordinal = next_ordinal_by_genre.get(genre_id, 0)

            next_ordinal_by_genre[genre_id] = max(
                next_ordinal_by_genre.get(genre_id, 0),
                ordinal + 1,
            )
            rows.append(
                PlaylistTrack(
                    genre_id=genre_id,
                    ordinal=ordinal,
                    song_title=title,
                    artist=artist,
                    youtube_url=youtube_url,
                    playlist_discovery_group=playlist_discovery_group,
                )
            )
    return rows


def _require_text(value: str | None, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _optional_text(value: str | None) -> str:
    return (value or "").strip()
