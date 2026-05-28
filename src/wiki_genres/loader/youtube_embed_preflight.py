"""YouTube embed preflight checks.

These checks aim to detect URLs that will fail iframe playback with
"Video unavailable / Watch on YouTube" and mark them as unembeddable.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx
from sqlalchemy import text

from wiki_genres.db import session_scope
from wiki_genres.db_migrations import apply_migrations

YOUTUBE_OEMBED = "https://www.youtube.com/oembed?format=json&url="
YOUTUBE_EMBED = "https://www.youtube.com/embed/"
YOUTUBEI_PLAYER = "https://www.youtube.com/youtubei/v1/player"
YOUTUBEI_KEY_BOOTSTRAP_VIDEO_ID = "dQw4w9WgXcQ"
YOUTUBEI_ANDROID_CLIENT = {
    "hl": "en",
    "gl": "US",
    "clientName": "ANDROID",
    "clientVersion": "20.10.38",
    "androidSdkVersion": 35,
    "userAgent": "com.google.android.youtube/20.10.38 (Linux; U; Android 15) gzip",
}
YOUTUBEI_BOT_OR_INTEGRITY_REASONS = (
    "bot",
    "reload",
    "sign in",
    "please sign in",
)


@dataclass(frozen=True)
class PreflightResult:
    youtube_url: str
    is_embeddable: bool | None
    checked_at: datetime
    http_status: int | None = None
    error: str = ""
    oembed_title: str = ""
    oembed_author: str = ""


@dataclass(frozen=True)
class PreflightStats:
    urls_seen: int
    urls_checked: int
    urls_cached: int
    urls_embeddable: int
    urls_unembeddable: int


@dataclass(frozen=True)
class EmbedShortfall:
    genre_id: str
    title: str
    usable_count: int
    blocked_count: int
    checked_count: int
    needed_count: int


@dataclass(frozen=True)
class YoutubeiProbeResult:
    is_embeddable: bool | None
    http_status: int | None
    error: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def extract_video_id(youtube_url: str) -> str:
    raw = (youtube_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if "youtu.be" in host:
        return path.strip("/").split("/")[0] if path.strip("/") else ""
    if "/embed/" in path:
        return path.split("/embed/")[1].split("/")[0]
    if "/shorts/" in path:
        return path.split("/shorts/")[1].split("/")[0]
    if "youtube.com" in host or "music.youtube.com" in host:
        values = query.get("v") or []
        return values[0] if values else ""
    return ""


_PLAYER_RESPONSE_RE = re.compile(r"ytInitialPlayerResponse\s*=\s*", re.DOTALL)
_INNERTUBE_API_KEY_RE = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')


def _parse_player_response(html: str) -> dict[str, Any] | None:
    match = _PLAYER_RESPONSE_RE.search(html)
    if not match:
        return None
    try:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(html[match.end() :])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _parse_innertube_api_key(html: str) -> str:
    match = _INNERTUBE_API_KEY_RE.search(html)
    return match.group(1) if match else ""


def _is_embed_playable(player_response: dict[str, Any]) -> tuple[bool, str]:
    status = (
        (player_response.get("playabilityStatus") or {})
        if isinstance(player_response, dict)
        else {}
    )
    code = str(status.get("status") or "")
    if code and code != "OK":
        reason = str(status.get("reason") or code).strip()
        return False, reason or code
    if status.get("playableInEmbed") is False:
        reason = str(status.get("reason") or "playableInEmbed=false").strip()
        return False, reason or "playableInEmbed=false"
    return True, ""


def _is_youtubei_player_decisive(player_response: dict[str, Any]) -> tuple[bool | None, str]:
    """Return decisive embed-relevant blocks from youtubei/v1/player.

    Browser-shaped WEB_EMBEDDED_PLAYER requests can false-negative without
    YouTube's live playback integrity tokens. The worker uses the mobile player
    response as a conservative probe: explicit non-embeddable and unavailable
    states are actionable, while generic bot/integrity responses remain unknown.
    """
    status = (
        (player_response.get("playabilityStatus") or {})
        if isinstance(player_response, dict)
        else {}
    )
    code = str(status.get("status") or "")
    reason = str(status.get("reason") or code).strip()
    normalized_reason = reason.lower()

    if code == "OK":
        if status.get("playableInEmbed") is False:
            return False, "youtubei playableInEmbed=false"
        return None, ""

    if not code:
        return None, "youtubei missing playabilityStatus"

    if any(marker in normalized_reason for marker in YOUTUBEI_BOT_OR_INTEGRITY_REASONS):
        return None, f"youtubei {code}: {reason or code}"

    return False, f"youtubei {code}: {reason or code}"


def _decision_for_http(result: PreflightResult) -> PreflightResult:
    """Return a stable decision, avoiding false negatives on transient errors."""
    status = result.http_status
    if status in {408, 425, 429} or (status is not None and status >= 500):
        return PreflightResult(
            youtube_url=result.youtube_url,
            is_embeddable=None,
            checked_at=result.checked_at,
            http_status=result.http_status,
            error=result.error,
            oembed_title=result.oembed_title,
            oembed_author=result.oembed_author,
        )
    return result


def _nullable_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


async def _fetch_oembed(
    client: httpx.AsyncClient,
    youtube_url: str,
) -> tuple[bool, int | None, str, str, str]:
    url = f"{YOUTUBE_OEMBED}{quote(youtube_url, safe='')}"
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return False, None, f"oembed error: {exc}", "", ""
    if resp.status_code != 200:
        return False, resp.status_code, f"oembed status {resp.status_code}", "", ""
    try:
        data = resp.json()
    except ValueError:
        return False, resp.status_code, "oembed invalid json", "", ""
    title = str(data.get("title") or "")
    author = str(data.get("author_name") or "")
    return True, resp.status_code, "", title, author


async def _fetch_embed_playability(
    client: httpx.AsyncClient,
    video_id: str,
) -> tuple[bool, int | None, str]:
    url = f"{YOUTUBE_EMBED}{quote(video_id, safe='')}"
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return False, None, f"embed error: {exc}"
    if resp.status_code != 200:
        return False, resp.status_code, f"embed status {resp.status_code}"
    parsed = _parse_player_response(resp.text)
    if not parsed:
        # Fallback: we couldn't parse the player response; treat as unknown-success.
        return True, resp.status_code, ""
    ok, reason = _is_embed_playable(parsed)
    return ok, resp.status_code, reason


async def _fetch_youtubei_api_key(client: httpx.AsyncClient) -> str:
    url = f"{YOUTUBE_EMBED}{YOUTUBEI_KEY_BOOTSTRAP_VIDEO_ID}"
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return ""
    if resp.status_code != 200:
        return ""
    return _parse_innertube_api_key(resp.text)


async def _fetch_youtubei_playability(
    client: httpx.AsyncClient,
    video_id: str,
    api_key: str,
) -> YoutubeiProbeResult:
    if not api_key:
        return YoutubeiProbeResult(
            is_embeddable=None,
            http_status=None,
            error="youtubei missing api key",
        )

    user_agent = str(YOUTUBEI_ANDROID_CLIENT["userAgent"])
    payload = {
        "context": {"client": YOUTUBEI_ANDROID_CLIENT},
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
        "thirdParty": {"embedUrl": "http://127.0.0.1:8765/explorer/"},
    }
    try:
        resp = await client.post(
            YOUTUBEI_PLAYER,
            params={"key": api_key, "prettyPrint": "false"},
            json=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
        )
    except httpx.HTTPError as exc:
        return YoutubeiProbeResult(
            is_embeddable=None,
            http_status=None,
            error=f"youtubei error: {exc}",
        )

    if resp.status_code != 200:
        return YoutubeiProbeResult(
            is_embeddable=None,
            http_status=resp.status_code,
            error=f"youtubei status {resp.status_code}",
        )

    try:
        data = resp.json()
    except ValueError:
        return YoutubeiProbeResult(
            is_embeddable=None,
            http_status=resp.status_code,
            error="youtubei invalid json",
        )

    decision, reason = _is_youtubei_player_decisive(data)
    return YoutubeiProbeResult(
        is_embeddable=decision,
        http_status=resp.status_code,
        error=reason,
    )


async def _preflight_youtube_urls(
    youtube_urls: list[str],
    *,
    concurrency: int = 64,
    ttl_days: int = 30,
    force: bool = False,
) -> list[PreflightResult]:
    """Preflight a batch of stored URLs and persist per-URL cache results."""
    await apply_migrations()
    ttl = timedelta(days=max(1, int(ttl_days)))
    cutoff = _now() - ttl
    unique_urls = []
    seen = set()
    for url in youtube_urls:
        cleaned = str(url or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique_urls.append(cleaned)

    if not unique_urls:
        return []

    cached: dict[str, PreflightResult] = {}
    if not force:
        async with session_scope() as session:
            cache_rows = (
                await session.execute(
                    text(
                        """
                        select youtube_url, is_embeddable, checked_at, http_status, error, oembed_title, oembed_author
                        from wg_youtube_embed_preflight_cache
                        where youtube_url = any(:urls)
                          and checked_at >= :cutoff
                        """
                    ),
                    {"urls": unique_urls, "cutoff": cutoff},
                )
            ).mappings()
            for row in cache_rows:
                cached[str(row["youtube_url"])] = PreflightResult(
                    youtube_url=str(row["youtube_url"]),
                    is_embeddable=_nullable_bool(row["is_embeddable"]),
                    checked_at=row["checked_at"],
                    http_status=int(row["http_status"]) if row["http_status"] is not None else None,
                    error=str(row["error"] or ""),
                    oembed_title=str(row["oembed_title"] or ""),
                    oembed_author=str(row["oembed_author"] or ""),
                )

    to_check = [url for url in unique_urls if force or url not in cached]

    limits = httpx.Limits(
        max_connections=max(10, concurrency * 2),
        max_keepalive_connections=max(10, concurrency),
    )
    timeout = httpx.Timeout(12.0, connect=8.0)
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _check_one(
        url: str,
        client: httpx.AsyncClient,
        youtubei_api_key: str,
    ) -> PreflightResult:
        async with semaphore:
            checked_at = _now()
            ok, status, err, title, author = await _fetch_oembed(client, url)
            if not ok:
                return PreflightResult(
                    youtube_url=url,
                    is_embeddable=False,
                    checked_at=checked_at,
                    http_status=status,
                    error=err,
                )

            video_id = extract_video_id(url)
            if not video_id:
                # Playlist-only URLs are hard to preflight reliably; accept if oEmbed worked.
                return PreflightResult(
                    youtube_url=url,
                    is_embeddable=True,
                    checked_at=checked_at,
                    http_status=status,
                    error="",
                    oembed_title=title,
                    oembed_author=author,
                )

            youtubei = await _fetch_youtubei_playability(client, video_id, youtubei_api_key)
            if youtubei.is_embeddable is False:
                return PreflightResult(
                    youtube_url=url,
                    is_embeddable=False,
                    checked_at=checked_at,
                    http_status=(
                        youtubei.http_status
                        if youtubei.http_status is not None
                        else status
                    ),
                    error=youtubei.error,
                    oembed_title=title,
                    oembed_author=author,
                )

            playable, embed_status, embed_err = await _fetch_embed_playability(client, video_id)
            http_status = embed_status if embed_status is not None else status
            return PreflightResult(
                youtube_url=url,
                is_embeddable=bool(playable),
                checked_at=checked_at,
                http_status=http_status,
                error=embed_err,
                oembed_title=title,
                oembed_author=author,
            )

    checked_results: list[PreflightResult] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": "wiki-genres/playlist-preflight"},
        follow_redirects=True,
        timeout=timeout,
        limits=limits,
    ) as client:
        youtubei_api_key = await _fetch_youtubei_api_key(client) if to_check else ""
        tasks = [_check_one(url, client, youtubei_api_key) for url in to_check]
        if tasks:
            checked_results = [_decision_for_http(r) for r in await asyncio.gather(*tasks)]

    combined = {**cached, **{r.youtube_url: r for r in checked_results}}
    await save_preflight_results(combined.values())
    return [combined[url] for url in unique_urls if url in combined]


async def save_preflight_results(results: Iterable[PreflightResult]) -> None:
    """Persist URL-level preflight results."""
    result_list = list(results)
    if not result_list:
        return
    async with session_scope() as session:
        for result in result_list:
            await session.execute(
                text(
                    """
                    insert into wg_youtube_embed_preflight_cache (
                        youtube_url, is_embeddable, checked_at, http_status, error, oembed_title, oembed_author
                    ) values (
                        :youtube_url, :is_embeddable, :checked_at, :http_status, :error, :oembed_title, :oembed_author
                    )
                    on conflict (youtube_url)
                    do update set
                        is_embeddable = excluded.is_embeddable,
                        checked_at = excluded.checked_at,
                        http_status = excluded.http_status,
                        error = excluded.error,
                        oembed_title = excluded.oembed_title,
                        oembed_author = excluded.oembed_author
                    """
                ),
                {
                    "youtube_url": result.youtube_url,
                    "is_embeddable": result.is_embeddable,
                    "checked_at": result.checked_at,
                    "http_status": result.http_status,
                    "error": result.error,
                    "oembed_title": result.oembed_title,
                    "oembed_author": result.oembed_author,
                },
            )


async def preflight_youtube_embeds(
    *,
    genre_id: str | None = None,
    concurrency: int = 64,
    ttl_days: int = 30,
    limit_urls: int | None = None,
    force: bool = False,
) -> PreflightStats:
    """Preflight YouTube playlist track URLs and persist results.

    Results are cached per-URL in `wg_youtube_embed_preflight_cache`.
    """
    await apply_migrations()
    ttl = timedelta(days=max(1, int(ttl_days)))
    cutoff = _now() - ttl

    async with session_scope() as session:
        sql = """
            select distinct tracks.youtube_url
            from wg_genre_approved_client_playlist_tracks tracks
            left join wg_youtube_embed_preflight_cache cache
              on cache.youtube_url = tracks.youtube_url
            where 1=1
        """
        params: dict[str, Any] = {"cutoff": cutoff, "limit_urls": limit_urls}
        if genre_id is not None:
            sql += " and tracks.genre_id = :genre_id"
            params["genre_id"] = genre_id
        if not force:
            sql += " and (cache.checked_at is null or cache.checked_at < :cutoff)"
        if limit_urls is not None:
            sql += " limit :limit_urls"

        rows = (await session.execute(text(sql), params)).scalars().all()

        youtube_urls = [str(url) for url in rows if str(url or "").strip()]

    if not youtube_urls:
        return PreflightStats(
            urls_seen=0,
            urls_checked=0,
            urls_cached=0,
            urls_embeddable=0,
            urls_unembeddable=0,
        )

    cached_count = 0
    if not force:
        async with session_scope() as session:
            cached_count = int(
                (
                    await session.execute(
                        text(
                            """
                            select count(*)
                            from wg_youtube_embed_preflight_cache
                            where youtube_url = any(:urls)
                              and checked_at >= :cutoff
                            """
                        ),
                        {"urls": youtube_urls, "cutoff": cutoff},
                    )
                ).scalar()
                or 0
            )

    results = await _preflight_youtube_urls(
        youtube_urls,
        concurrency=concurrency,
        ttl_days=ttl_days,
        force=force,
    )
    embeddable = sum(1 for r in results if r.is_embeddable is True)
    unembeddable = sum(1 for r in results if r.is_embeddable is False)
    return PreflightStats(
        urls_seen=len(youtube_urls),
        urls_checked=len(youtube_urls) if force else max(0, len(youtube_urls) - cached_count),
        urls_cached=0 if force else cached_count,
        urls_embeddable=embeddable,
        urls_unembeddable=unembeddable,
    )


async def playlist_embed_shortfalls(*, target_count: int = 35) -> list[EmbedShortfall]:
    """Return genres that need another translation pass after embed preflight."""
    await apply_migrations()
    async with session_scope() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT
                        g.id AS genre_id,
                        g.wikipedia_title AS title,
                        count(*) AS usable_count,
                        count(*) FILTER (
                            WHERE cache.is_embeddable = false
                        ) AS blocked_count,
                        count(*) FILTER (
                            WHERE cache.checked_at IS NOT NULL
                        ) AS checked_count
                    FROM wg_genre_approved_client_playlist_tracks t
                    JOIN wg_genres g ON g.id = t.genre_id
                    LEFT JOIN wg_youtube_embed_preflight_cache cache
                      ON cache.youtube_url = t.youtube_url
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                    GROUP BY g.id, g.wikipedia_title
                    HAVING count(*) < :target_count
                    ORDER BY
                        (:target_count - count(*)) DESC,
                        usable_count,
                        g.wikipedia_title
                """),
                {"target_count": int(target_count)},
            )
        ).mappings()

        out: list[EmbedShortfall] = []
        for row in rows:
            usable_count = int(row["usable_count"] or 0)
            out.append(
                EmbedShortfall(
                    genre_id=str(row["genre_id"]),
                    title=str(row["title"]),
                    usable_count=usable_count,
                    blocked_count=int(row["blocked_count"] or 0),
                    checked_count=int(row["checked_count"] or 0),
                    needed_count=max(0, int(target_count) - usable_count),
                )
            )
        return out
