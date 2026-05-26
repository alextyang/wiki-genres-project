"""Two-pass database loader.

Pass 1 — ``load_genre()``: upserts a genre node + all its denormalized data
(aliases, origins, instruments, categories, edges with raw labels).

Pass 2 — ``resolve_edges()``: iterates over every ``wg_edges`` row where
``to_genre_id IS NULL`` and tries to link it to a known genre via title
match → redirect lookup → Wikidata QID match.

Both passes are idempotent; re-running after a partial failure converges.
"""

from __future__ import annotations

import json
import re

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.parser.types import ParsedEdge, ParsedGenre, ParsedWikidataEntity

logger = structlog.get_logger(__name__)


def _genre_id(qid: str | None, title: str) -> str:
    """Stable internal ID.  Prefer QID-based; fall back to title slug."""
    if qid:
        return f"wg-{qid.lower()}"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"wg-title-{slug}"


# ------------------------------------------------------------------ #
# Pass 1: load one genre                                               #
# ------------------------------------------------------------------ #


async def load_genre(
    parsed: ParsedGenre,
    wikidata: ParsedWikidataEntity | None = None,
    triggered_by: str = "bootstrap",
) -> str:
    """Upsert a genre and all its related rows. Returns the genre ``id``."""
    genre_id = _genre_id(parsed.wikidata_qid, parsed.wikipedia_title)
    engine = get_engine()

    # Snapshot pre-update state so we can compute a revision diff.
    async with engine.connect() as conn:
        pre = (
            (
                await conn.execute(
                    text("""
                SELECT raw_wikitext_sha256,
                       (SELECT count(*) FROM wg_edges   WHERE from_genre_id = :id) AS edge_count,
                       (SELECT count(*) FROM wg_aliases WHERE genre_id       = :id) AS alias_count
                FROM wg_genres WHERE id = :id
            """),
                    {"id": genre_id},
                )
            )
            .mappings()
            .fetchone()
        )

    old_sha = pre["raw_wikitext_sha256"] if pre else None
    old_edges = int(pre["edge_count"]) if pre else 0
    old_aliases = int(pre["alias_count"]) if pre else 0

    async with engine.begin() as conn:
        # Core genre row — clear deleted_at on successful re-fetch.
        await conn.execute(
            text("""
                insert into wg_genres (
                    id, wikidata_qid, wikipedia_title, wikipedia_url,
                    summary, infobox_color, is_seed, has_infobox,
                    raw_wikitext_sha256, upstream_revision,
                    first_seen_at, last_fetched_at, last_changed_at,
                    deleted_at
                )
                values (
                    :id, :qid, :title, :url,
                    :summary, :color, :is_seed, :has_infobox,
                    :sha256, :revision,
                    now(), now(), now(),
                    null
                )
                on conflict (id) do update set
                    wikidata_qid        = excluded.wikidata_qid,
                    wikipedia_title     = excluded.wikipedia_title,
                    wikipedia_url       = excluded.wikipedia_url,
                    summary             = excluded.summary,
                    infobox_color       = excluded.infobox_color,
                    has_infobox         = excluded.has_infobox,
                    raw_wikitext_sha256 = excluded.raw_wikitext_sha256,
                    upstream_revision   = excluded.upstream_revision,
                    last_fetched_at     = now(),
                    deleted_at          = null,
                    last_changed_at     = case
                        when wg_genres.raw_wikitext_sha256
                            is distinct from excluded.raw_wikitext_sha256
                        then now()
                        else wg_genres.last_changed_at
                    end
            """),
            {
                "id": genre_id,
                "qid": parsed.wikidata_qid,
                "title": parsed.wikipedia_title,
                "url": parsed.wikipedia_url,
                "summary": parsed.summary,
                "color": parsed.infobox_color,
                "is_seed": False,
                "has_infobox": parsed.has_infobox,
                "sha256": parsed.raw_wikitext_sha256,
                "revision": parsed.upstream_revision,
            },
        )

        # Aliases from infobox other_names.
        for alias in parsed.aliases:
            await conn.execute(
                text("""
                    insert into wg_aliases (genre_id, alias, source, first_seen_at)
                    values (:genre_id, :alias, 'other_names', now())
                    on conflict (genre_id, alias, source) do nothing
                """),
                {"genre_id": genre_id, "alias": alias},
            )

        # Aliases from Wikidata.
        if wikidata:
            for alias in wikidata.aliases:
                await conn.execute(
                    text("""
                        insert into wg_aliases (genre_id, alias, source, first_seen_at)
                        values (:genre_id, :alias, 'wikidata_alias', now())
                        on conflict (genre_id, alias, source) do nothing
                    """),
                    {"genre_id": genre_id, "alias": alias},
                )

        # Origins.
        for origin in parsed.origins:
            await conn.execute(
                text("""
                    insert into wg_origins (
                        genre_id, kind, value,
                        parsed_year_start, parsed_year_end, parsed_region
                    )
                    values (:gid, :kind, :value, :ys, :ye, :region)
                    on conflict (genre_id, kind, value) do nothing
                """),
                {
                    "gid": genre_id,
                    "kind": origin.kind,
                    "value": origin.value,
                    "ys": origin.parsed_year_start,
                    "ye": origin.parsed_year_end,
                    "region": origin.parsed_region,
                },
            )

        # Instruments.
        for instrument in parsed.instruments:
            await conn.execute(
                text("""
                    insert into wg_instruments (genre_id, instrument)
                    values (:gid, :inst)
                    on conflict (genre_id, instrument) do nothing
                """),
                {"gid": genre_id, "inst": instrument},
            )

        # Categories.
        for cat in parsed.categories:
            await conn.execute(
                text("""
                    insert into wg_categories (genre_id, category)
                    values (:gid, :cat)
                    on conflict (genre_id, category) do nothing
                """),
                {"gid": genre_id, "cat": cat},
            )

        # Edges — infobox. Delete-then-insert so a re-fetch fully refreshes them.
        await conn.execute(
            text("delete from wg_edges where from_genre_id = :gid and source = 'infobox'"),
            {"gid": genre_id},
        )
        all_edges: list[ParsedEdge] = list(parsed.infobox_edges)
        if wikidata:
            await conn.execute(
                text("delete from wg_edges where from_genre_id = :gid and source = 'wikidata'"),
                {"gid": genre_id},
            )
            all_edges.extend(wikidata.edges)

        for edge in all_edges:
            to_genre_id = await _resolve_target(conn, edge, genre_id)
            await conn.execute(
                text("""
                    insert into wg_edges (
                        from_genre_id, to_genre_id, to_raw_label,
                        relation, source, ordinal, first_seen_at
                    )
                    values (
                        :from_id, :to_id, :raw_label,
                        :relation, :source, :ordinal, now()
                    )
                    on conflict (from_genre_id, relation, source, ordinal) do update set
                        to_genre_id  = excluded.to_genre_id,
                        to_raw_label = excluded.to_raw_label
                """),
                {
                    "from_id": genre_id,
                    "to_id": to_genre_id,
                    # Prefer wiki_target for resolution; fall back to display label.
                    "raw_label": edge.wiki_target or edge.raw_label,
                    "relation": edge.relation,
                    "source": edge.source,
                    "ordinal": edge.ordinal,
                },
            )

    # Record a revision entry when content changes on a re-fetch.
    new_sha = parsed.raw_wikitext_sha256
    if old_sha is not None and old_sha != new_sha and parsed.upstream_revision:
        await _record_revision(engine, genre_id, parsed, triggered_by, old_edges, old_aliases)

    logger.debug("genre_loaded", genre_id=genre_id, title=parsed.wikipedia_title)
    return genre_id


async def _record_revision(
    engine,
    genre_id: str,
    parsed: ParsedGenre,
    triggered_by: str,
    old_edges: int,
    old_aliases: int,
) -> None:
    """Insert a wg_revisions row capturing what changed on this fetch."""
    async with engine.connect() as conn:
        new_edges = (
            await conn.scalar(
                text("SELECT count(*) FROM wg_edges WHERE from_genre_id = :id"),
                {"id": genre_id},
            )
        ) or 0
        new_aliases = (
            await conn.scalar(
                text("SELECT count(*) FROM wg_aliases WHERE genre_id = :id"),
                {"id": genre_id},
            )
        ) or 0

    diff = {
        "edges_before": old_edges,
        "edges_after": int(new_edges),
        "edges_delta": int(new_edges) - old_edges,
        "aliases_before": old_aliases,
        "aliases_after": int(new_aliases),
        "aliases_delta": int(new_aliases) - old_aliases,
    }

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO wg_revisions (
                    genre_id, upstream_revision, fetched_at,
                    content_sha256, triggered_by, diff_summary
                )
                VALUES (
                    :gid, :rev, now(),
                    :sha, :by, :diff
                )
                ON CONFLICT (genre_id, upstream_revision) DO UPDATE SET
                    diff_summary = excluded.diff_summary,
                    triggered_by = excluded.triggered_by
            """),
            {
                "gid": genre_id,
                "rev": parsed.upstream_revision,
                "sha": parsed.raw_wikitext_sha256,
                "by": triggered_by,
                "diff": json.dumps(diff),
            },
        )
    logger.info(
        "revision_recorded",
        genre_id=genre_id,
        edges_delta=diff["edges_delta"],
        aliases_delta=diff["aliases_delta"],
    )


# ------------------------------------------------------------------ #
# Pageviews                                                            #
# ------------------------------------------------------------------ #


async def load_pageviews(genre_id: str, items: list[dict]) -> None:
    """Upsert monthly pageview rows and refresh wg_genres.monthly_views_p30."""
    parsed: list[tuple[int, int, int]] = []
    for item in items:
        ts = item.get("timestamp", "")
        if len(ts) >= 6:
            try:
                parsed.append((int(ts[:4]), int(ts[4:6]), int(item.get("views", 0))))
            except (ValueError, TypeError):
                continue

    if not parsed:
        return

    engine = get_engine()
    async with engine.begin() as conn:
        for year, month, views in parsed:
            await conn.execute(
                text("""
                    INSERT INTO wg_pageviews (genre_id, year, month, views, fetched_at)
                    VALUES (:gid, :year, :month, :views, now())
                    ON CONFLICT (genre_id, year, month) DO UPDATE SET
                        views      = excluded.views,
                        fetched_at = now()
                """),
                {"gid": genre_id, "year": year, "month": month, "views": views},
            )

        most_recent = max(parsed, key=lambda x: (x[0], x[1]))
        await conn.execute(
            text("UPDATE wg_genres SET monthly_views_p30 = :v WHERE id = :id"),
            {"id": genre_id, "v": most_recent[2]},
        )

    logger.debug("pageviews_loaded", genre_id=genre_id, months=len(parsed))


# ------------------------------------------------------------------ #
# Pass 2: resolve unlinked edges                                       #
# ------------------------------------------------------------------ #


async def resolve_edges() -> int:
    """Attempt to fill ``to_genre_id`` for every unresolved edge.

    Returns the number of edges newly resolved.
    """
    engine = get_engine()
    resolved = 0

    async with engine.begin() as conn:
        rows = await conn.execute(
            text("""
                select from_genre_id, relation, source, ordinal, to_raw_label
                from wg_edges
                where to_genre_id is null
            """)
        )
        unresolved = rows.fetchall()

    for row in unresolved:
        async with engine.begin() as conn:
            edge = ParsedEdge(
                relation=row.relation,
                raw_label=row.to_raw_label,
                # to_raw_label already stores the wiki_target when available.
                wiki_target=row.to_raw_label,
                source=row.source,
                ordinal=row.ordinal,
            )
            to_id = await _resolve_target(conn, edge, row.from_genre_id)
            if to_id is None:
                continue
            await conn.execute(
                text("""
                    update wg_edges
                    set to_genre_id = :to_id
                    where from_genre_id = :from_id
                      and relation = :rel
                      and source = :src
                      and ordinal = :ord
                """),
                {
                    "to_id": to_id,
                    "from_id": row.from_genre_id,
                    "rel": row.relation,
                    "src": row.source,
                    "ord": row.ordinal,
                },
            )
            resolved += 1

    logger.info("edges_resolved", count=resolved)
    return resolved


async def _resolve_target(conn: object, edge: ParsedEdge, from_id: str) -> str | None:
    """Try to find the ``wg_genres.id`` for an edge's target.

    Resolution order:
    1. Wikipedia title exact match (for infobox edges).
    2. Redirect lookup in ``wg_redirects``.
    3. Wikidata QID match (for Wikidata edges where raw_label is a QID).
    Returns None if no match found — the edge stays unresolved for pass 2.
    """
    target = edge.wiki_target or edge.raw_label

    # 1. Direct title match.
    if target and not target.startswith("wg-"):
        row = await conn.scalar(  # type: ignore[attr-defined]
            text("select id from wg_genres where wikipedia_title = :t"),
            {"t": target},
        )
        if row:
            return row

    # 2. Redirect lookup.
    if target:
        row = await conn.scalar(  # type: ignore[attr-defined]
            text("select to_genre_id from wg_redirects where from_title = :t"),
            {"t": target},
        )
        if row:
            return row

    # 3. QID match (Wikidata edges have raw_label like "Q188450").
    if edge.source == "wikidata" and edge.raw_label.startswith("Q"):
        candidate_id = f"wg-{edge.raw_label.lower()}"
        exists = await conn.scalar(  # type: ignore[attr-defined]
            text("select 1 from wg_genres where id = :id"),
            {"id": candidate_id},
        )
        if exists:
            return candidate_id

    return None


# ------------------------------------------------------------------ #
# Fetch-log helper                                                     #
# ------------------------------------------------------------------ #


async def log_fetch(
    url: str, http_status: int, content_sha256: str | None, elapsed_ms: int, via: str
) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                insert into wg_fetch_log (url, fetched_at, http_status, content_sha256,
                                          elapsed_ms, via)
                values (:url, now(), :status, :sha, :elapsed, :via)
            """),
            {
                "url": url,
                "status": http_status,
                "sha": content_sha256,
                "elapsed": elapsed_ms,
                "via": via,
            },
        )
