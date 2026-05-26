"""Tests for YouTube embed preflight decisions."""

from __future__ import annotations

from datetime import datetime, timezone

from wiki_genres.loader.youtube_embed_preflight import (
    PreflightResult,
    _decision_for_http,
    _is_embed_playable,
    _nullable_bool,
    _parse_player_response,
    extract_video_id,
)


def test_extract_video_id_accepts_common_youtube_urls() -> None:
    assert extract_video_id("https://www.youtube.com/watch?v=abc123&list=PLx") == "abc123"
    assert extract_video_id("https://music.youtube.com/watch?v=abc123") == "abc123"
    assert extract_video_id("https://youtu.be/abc123?t=30") == "abc123"
    assert extract_video_id("https://www.youtube.com/embed/abc123") == "abc123"
    assert extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"


def test_parse_player_response_handles_nested_json() -> None:
    parsed = _parse_player_response(
        'ytInitialPlayerResponse = {"playabilityStatus":{"status":"OK"},'
        '"videoDetails":{"title":"A } tricky title"}};'
    )

    assert parsed
    assert parsed["videoDetails"]["title"] == "A } tricky title"


def test_embed_playable_rejects_non_ok_and_embed_blocks() -> None:
    assert _is_embed_playable({"playabilityStatus": {"status": "OK"}}) == (True, "")
    assert _is_embed_playable({"playabilityStatus": {"status": "ERROR", "reason": "Unavailable"}}) == (
        False,
        "Unavailable",
    )
    assert _is_embed_playable({"playabilityStatus": {"status": "OK", "playableInEmbed": False}}) == (
        False,
        "playableInEmbed=false",
    )


def test_transient_preflight_result_stays_unknown() -> None:
    result = PreflightResult(
        youtube_url="https://www.youtube.com/watch?v=abc123",
        is_embeddable=False,
        checked_at=datetime.now(timezone.utc),
        http_status=429,
        error="oembed status 429",
    )

    assert _decision_for_http(result).is_embeddable is None


def test_nullable_bool_preserves_unknown_cached_state() -> None:
    assert _nullable_bool(None) is None
    assert _nullable_bool(False) is False
    assert _nullable_bool(True) is True
