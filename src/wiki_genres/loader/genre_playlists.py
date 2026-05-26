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
    await apply_migrations()
    title = _require_text(song_title, "song title")
    artist_name = _optional_text(artist)
    url = validate_youtube_url(youtube_url)
    group = _optional_text(playlist_discovery_group) or DEFAULT_PLAYLIST_DISCOVERY_GROUP

    async with session_scope() as session:
        genre_exists = await session.scalar(
            text("""
                SELECT 1
                FROM wg_genres
                WHERE id = :genre_id
                  AND deleted_at IS NULL
                  AND is_non_genre = false
            """),
            {"genre_id": genre_id},
        )
        if not genre_exists:
            raise ValueError(f"Active genre not found: {genre_id}")

        if ordinal is None:
            next_ordinal = await session.scalar(
                text("""
                    SELECT coalesce(max(ordinal), -1) + 1
                    FROM wg_genre_youtube_playlist_tracks
                    WHERE genre_id = :genre_id
                """),
                {"genre_id": genre_id},
            )
            ordinal = int(next_ordinal or 0)
        if ordinal < 0:
            raise ValueError("ordinal must be non-negative")

        await session.execute(
            text("""
                INSERT INTO wg_genre_youtube_playlist_tracks (
                    genre_id,
                    ordinal,
                    song_title,
                    artist,
                    youtube_url,
                    playlist_discovery_group
                )
                VALUES (
                    :genre_id,
                    :ordinal,
                    :song_title,
                    :artist,
                    :youtube_url,
                    :playlist_discovery_group
                )
                ON CONFLICT (genre_id, ordinal)
                DO UPDATE SET
                    song_title = excluded.song_title,
                    artist = excluded.artist,
                    youtube_url = excluded.youtube_url,
                    playlist_discovery_group = excluded.playlist_discovery_group
            """),
            {
                "genre_id": genre_id,
                "ordinal": ordinal,
                "song_title": title,
                "artist": artist_name,
                "youtube_url": url,
                "playlist_discovery_group": group,
            },
        )

    return PlaylistTrack(
        genre_id=genre_id,
        ordinal=ordinal,
        song_title=title,
        artist=artist_name,
        youtube_url=url,
        playlist_discovery_group=group,
    )


async def list_playlist_tracks(genre_id: str) -> list[PlaylistTrack]:
    """Return the curated YouTube playlist for a genre."""
    await apply_migrations()
    async with session_scope() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT genre_id, ordinal, song_title, artist, youtube_url, playlist_discovery_group
                    FROM wg_genre_youtube_playlist_tracks
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
                playlist_discovery_group=str(row["playlist_discovery_group"]),
            )
            for row in rows
        ]


async def import_playlist_csv(path: Path, *, replace_genres: bool = False) -> PlaylistImportStats:
    """Import curated playlist rows from a local CSV file."""
    await apply_migrations()
    rows = _read_playlist_csv(path)
    if not rows:
        return PlaylistImportStats(rows_read=0, rows_written=0, genres_touched=0)

    genres = {row.genre_id for row in rows}

    async with session_scope() as session:
        existing_genres = set(
            (
                await session.execute(
                    text("""
                        SELECT id
                        FROM wg_genres
                        WHERE id = ANY(:genre_ids)
                          AND deleted_at IS NULL
                          AND is_non_genre = false
                    """),
                    {"genre_ids": sorted(genres)},
                )
            ).scalars()
        )
        missing = sorted(genres - existing_genres)
        if missing:
            raise ValueError(f"Active genre not found: {', '.join(missing)}")

        if replace_genres:
            await session.execute(
                text("""
                    DELETE FROM wg_genre_youtube_playlist_tracks
                    WHERE genre_id = ANY(:genre_ids)
                """),
                {"genre_ids": sorted(genres)},
            )

        for row in rows:
            await session.execute(
                text("""
                    INSERT INTO wg_genre_youtube_playlist_tracks (
                        genre_id,
                        ordinal,
                        song_title,
                        artist,
                        youtube_url,
                        playlist_discovery_group
                    )
                    VALUES (
                        :genre_id,
                        :ordinal,
                        :song_title,
                        :artist,
                        :youtube_url,
                        :playlist_discovery_group
                    )
                    ON CONFLICT (genre_id, ordinal)
                    DO UPDATE SET
                        song_title = excluded.song_title,
                        artist = excluded.artist,
                        youtube_url = excluded.youtube_url,
                        playlist_discovery_group = excluded.playlist_discovery_group
                """),
                {
                    "genre_id": row.genre_id,
                    "ordinal": row.ordinal,
                    "song_title": row.song_title,
                    "artist": row.artist,
                    "youtube_url": row.youtube_url,
                    "playlist_discovery_group": row.playlist_discovery_group,
                },
            )

    return PlaylistImportStats(
        rows_read=len(rows),
        rows_written=len(rows),
        genres_touched=len(genres),
    )


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
