"""Feedback webhook forwarding."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from wiki_genres.api.models import FeedbackPayload, FeedbackResult, YoutubePlaybackErrorPayload
from wiki_genres.config import get_settings
from wiki_genres.db import session_scope

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


def _feedback_text(payload: FeedbackPayload) -> str:
    parts = [
        f"wiki-genres feedback: {payload.report_type}",
        f"Genre: {payload.genre_name or 'unknown'} ({payload.genre_id or 'no id'})",
    ]
    if payload.relationship:
        parts.append(f"Relationship: {payload.relationship}")
    if payload.youtube_url:
        parts.append(f"YouTube: {payload.youtube_title or payload.youtube_url}")
    if payload.youtube_artist:
        parts.append(f"Artist: {payload.youtube_artist}")
    if payload.notes:
        parts.append(f"Notes: {payload.notes}")
    if payload.graph_path:
        parts.append(f"Path: {payload.graph_path}")
    if payload.page_url:
        parts.append(f"Page: {payload.page_url}")
    return "\n".join(parts)


@router.post("", response_model=FeedbackResult)
async def submit_feedback(payload: FeedbackPayload) -> FeedbackResult:
    """Forward user feedback to the configured webhook."""
    webhook_url = get_settings().feedback_webhook_url
    if not webhook_url:
        raise HTTPException(status_code=503, detail="Feedback webhook is not configured")

    body = payload.model_dump(mode="json")
    body["content"] = _feedback_text(payload)
    body["text"] = body["content"]

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(webhook_url, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Feedback webhook returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Feedback webhook request failed") from exc

    return FeedbackResult(ok=True)


@router.post("/youtube-error", response_model=FeedbackResult)
async def submit_youtube_playback_error(payload: YoutubePlaybackErrorPayload) -> FeedbackResult:
    """Record client-observed YouTube iframe playback failures."""
    youtube_url = payload.youtube_url.strip()
    genre_id = payload.genre_id.strip()
    if not youtube_url or not genre_id:
        raise HTTPException(status_code=400, detail="genre_id and youtube_url are required")

    async with session_scope() as session:
        exists = await session.scalar(
            text("""
                SELECT 1
                FROM wg_genre_youtube_playlist_tracks
                WHERE genre_id = :genre_id
                  AND youtube_url = :youtube_url
            """),
            {"genre_id": genre_id, "youtube_url": youtube_url},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Playlist track not found")

        await session.execute(
            text("""
                INSERT INTO wg_youtube_playback_error_stats (
                    genre_id,
                    youtube_url,
                    error_count,
                    last_error,
                    last_title,
                    last_artist,
                    last_page_url
                )
                VALUES (
                    :genre_id,
                    :youtube_url,
                    1,
                    :last_error,
                    :last_title,
                    :last_artist,
                    :last_page_url
                )
                ON CONFLICT (genre_id, youtube_url)
                DO UPDATE SET
                    error_count = wg_youtube_playback_error_stats.error_count + 1,
                    last_seen_at = now(),
                    last_error = excluded.last_error,
                    last_title = excluded.last_title,
                    last_artist = excluded.last_artist,
                    last_page_url = excluded.last_page_url
            """),
            {
                "genre_id": genre_id,
                "youtube_url": youtube_url,
                "last_error": payload.error,
                "last_title": payload.youtube_title,
                "last_artist": payload.youtube_artist,
                "last_page_url": payload.page_url,
            },
        )

    return FeedbackResult(ok=True)
