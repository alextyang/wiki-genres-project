"""Materialize country-to-genre affinity signals for country cloud layouts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_ownership import DEMONYM_OVERRIDES, title_is_region_specific

logger = structlog.get_logger(__name__)

AFFINITY_MODEL = "deterministic-country-affinity-v1"
MUSIC_REGION_TITLE_RE = re.compile(r"\bmusic\s+(?:of|in)\b", re.IGNORECASE)
WIKILINK_RE = re.compile(r"\[\[([^]|#]+)(?:#[^]|]+)?(?:\|([^]]+))?\]\]")
TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CountryRegion:
    region_id: str
    canonical_name: str
    wikipedia_title: str | None
    promoted_genre_id: str | None
    promoted_title: str | None
    aliases: tuple[str, ...]


@dataclass
class AffinityEvidence:
    source: str
    score: float
    confidence: float
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CountryAffinityStats:
    genres_seen: int = 0
    countries_seen: int = 0
    content_cached: int = 0
    content_fetched: int = 0
    content_failed: int = 0
    affinities_written: int = 0
    deleted_existing: int = 0
    dry_run: bool = False
    source_distribution: dict[str, int] = field(default_factory=dict)
    sample: list[str] = field(default_factory=list)


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.]+", " ", (value or "").lower())).strip()


def _tokens(value: str | None) -> set[str]:
    return set(TOKEN_RE.findall(_norm(value)))


def _strip_music_prefix(value: str | None) -> str:
    text_value = re.sub(r"\s+", " ", (value or "").strip())
    lowered = text_value.lower()
    for prefix in (
        "music of the ",
        "music of ",
        "music in the ",
        "music in ",
        "traditional music of the ",
        "traditional music of ",
    ):
        if lowered.startswith(prefix):
            return text_value[len(prefix) :]
    return text_value


def _plain_wikitext(value: str | None, *, limit: int = 32000) -> str:
    text_value = str(value or "")
    if not text_value:
        return ""
    text_value = REF_RE.sub(" ", text_value)
    text_value = TEMPLATE_RE.sub(" ", text_value)
    text_value = TAG_RE.sub(" ", text_value)
    text_value = WIKILINK_RE.sub(lambda m: f"{m.group(1)} {m.group(2) or ''}", text_value)
    text_value = re.sub(r"'{2,}", "", text_value)
    text_value = re.sub(r"\s+", " ", text_value)
    return text_value[:limit]


def _contains_alias(text_norm: str, alias: str) -> bool:
    alias_norm = _norm(alias)
    if not alias_norm:
        return False
    if alias_norm in {"us", "u.s."}:
        return bool(re.search(r"\b(?:u\.s\.|us|united states)\b", text_norm))
    return bool(re.search(rf"\b{re.escape(alias_norm)}\b", text_norm))


def _alias_count(text_norm: str, aliases: tuple[str, ...]) -> int:
    return sum(1 for alias in aliases if _contains_alias(text_norm, alias))


def _country_aliases(row: dict[str, Any]) -> tuple[str, ...]:
    candidates = {
        row["canonical_name"],
        _strip_music_prefix(row.get("wikipedia_title")),
        _strip_music_prefix(row.get("promoted_title")),
    }
    normalized_name = _norm(row["canonical_name"])
    candidates.update(DEMONYM_OVERRIDES.get(normalized_name, set()))
    if normalized_name == "united states":
        candidates.update({"American", "United States", "U.S.", "US"})
    elif normalized_name == "united kingdom":
        candidates.update({"British", "UK", "United Kingdom"})
    elif normalized_name == "south korea":
        candidates.update({"Korean", "South Korean"})
    elif normalized_name == "north korea":
        candidates.update({"Korean", "North Korean"})
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = _norm(item)
        if not normalized or normalized in seen:
            continue
        if len(normalized) < 3 and normalized not in {"us", "uk"}:
            continue
        seen.add(normalized)
        out.append(item)
    return tuple(out)


async def _load_countries(conn: object) -> list[CountryRegion]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT
                        r.id AS region_id,
                        r.canonical_name,
                        r.wikipedia_title,
                        p.genre_id AS promoted_genre_id,
                        p.wikipedia_title AS promoted_title
                    FROM wg_regions r
                    LEFT JOIN wg_region_promoted_genres p ON p.region_id = r.id
                    WHERE r.kind = 'country'
                    ORDER BY r.canonical_name
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        CountryRegion(
            region_id=row["region_id"],
            canonical_name=row["canonical_name"],
            wikipedia_title=row["wikipedia_title"],
            promoted_genre_id=row["promoted_genre_id"],
            promoted_title=row["promoted_title"],
            aliases=_country_aliases(dict(row)),
        )
        for row in rows
    ]


async def _load_region_country_map(conn: object) -> dict[str, set[str]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    WITH RECURSIVE country_tree AS (
                        SELECT id AS country_region_id, id AS region_id
                        FROM wg_regions
                        WHERE kind = 'country'

                        UNION ALL

                        SELECT tree.country_region_id, child.id AS region_id
                        FROM country_tree tree
                        JOIN wg_region_relationships rel ON rel.to_region_id = tree.region_id
                        JOIN wg_regions child ON child.id = rel.from_region_id
                        WHERE rel.status = 'accepted'
                    )
                    SELECT country_region_id, region_id
                    FROM country_tree
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    mapping: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        mapping[row["region_id"]].add(row["country_region_id"])
    return mapping


async def _load_genres(conn: object, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT id, wikipedia_title, summary, monthly_views_p30
                    FROM wg_genres
                    WHERE deleted_at IS NULL
                      AND is_non_genre = false
                    ORDER BY wikipedia_title
                    LIMIT coalesce(:limit_value, 2147483647)
                """),
                {"limit_value": limit},
            )
        )
        .mappings()
        .fetchall()
    )
    return [dict(row) for row in rows]


async def _load_grouped_text(conn: object, table: str, column: str) -> dict[str, list[str]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text(f"""
                    SELECT genre_id, {column} AS value
                    FROM {table}
                    ORDER BY genre_id, value
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[row["genre_id"]].append(row["value"])
    return grouped


async def _load_existing_relationship_evidence(
    conn: object,
    *,
    region_to_countries: dict[str, set[str]],
) -> dict[tuple[str, str], list[AffinityEvidence]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT
                        rel.region_id,
                        rel.genre_id,
                        rel.relation,
                        rel.source_type,
                        rel.evidence_text,
                        rel.confidence,
                        rel.status
                    FROM wg_region_genre_relationships rel
                    WHERE rel.status = 'accepted'
                      AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    out: dict[tuple[str, str], list[AffinityEvidence]] = defaultdict(list)
    for row in rows:
        for country_id in region_to_countries.get(row["region_id"], {row["region_id"]}):
            out[(row["genre_id"], country_id)].append(
                AffinityEvidence(
                    source="accepted_region_relationship",
                    score=0.94,
                    confidence=max(0.72, min(1.0, float(row["confidence"] or 0.72))),
                    text=row["evidence_text"] or f"Accepted {row['relation']} relationship.",
                    payload={
                        "source_region_id": row["region_id"],
                        "relation": row["relation"],
                        "source_type": row["source_type"],
                    },
                )
            )
    return out


async def _load_promoted_child_evidence(conn: object) -> dict[tuple[str, str], list[AffinityEvidence]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT
                        p.region_id,
                        edge.to_genre_id AS genre_id,
                        edge.relation,
                        parent.wikipedia_title AS parent_title,
                        child.wikipedia_title AS child_title
                    FROM wg_region_promoted_genres p
                    JOIN wg_relationship_traversal_edges edge ON edge.from_genre_id = p.genre_id
                    JOIN wg_genres parent ON parent.id = p.genre_id
                    JOIN wg_genres child ON child.id = edge.to_genre_id
                    JOIN wg_regions r ON r.id = p.region_id
                    WHERE r.kind = 'country'
                      AND edge.is_ignored = false
                      AND edge.to_genre_id IS NOT NULL
                      AND child.deleted_at IS NULL
                      AND child.is_non_genre = false
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    out: dict[tuple[str, str], list[AffinityEvidence]] = defaultdict(list)
    for row in rows:
        out[(row["genre_id"], row["region_id"])].append(
            AffinityEvidence(
                source="country_music_page_child",
                score=0.9,
                confidence=0.82,
                text=f"{row['child_title']} is linked as {row['relation']} from {row['parent_title']}.",
                payload={"relation": row["relation"], "source_title": row["parent_title"]},
            )
        )
    return out


async def _load_content_cache(conn: object) -> dict[str, str]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT wikipedia_title, wikitext
                    FROM wg_wikipedia_page_content_cache
                    WHERE fetch_status = 'ok'
                      AND wikitext IS NOT NULL
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    return {row["wikipedia_title"]: row["wikitext"] for row in rows}


async def ensure_wikipedia_page_content_cache(
    *,
    titles: list[str],
    from_cache: bool = False,
    limit: int | None = None,
) -> CountryAffinityStats:
    """Fetch/store wikitext for titles missing from the local DB content cache."""
    await apply_migrations()
    engine = get_engine()
    stats = CountryAffinityStats()
    unique_titles = []
    seen = set()
    for title in titles:
        if not title or title in seen:
            continue
        seen.add(title)
        unique_titles.append(title)
    if limit is not None:
        unique_titles = unique_titles[:limit]

    async with engine.connect() as conn:
        existing = set(
            (
                await conn.execute(
                    text("""
                        SELECT wikipedia_title
                        FROM wg_wikipedia_page_content_cache
                        WHERE wikipedia_title = ANY(:titles)
                    """),
                    {"titles": unique_titles},
                )
            )
            .scalars()
            .all()
        )
    missing = [title for title in unique_titles if title not in existing]
    stats.content_cached = len(existing)

    fetcher = WikiFetcher(from_cache=from_cache)
    try:
        for title in missing:
            result = await fetcher.fetch_wikitext(title)
            raw_payload: dict[str, Any] = {"url": result.url, "from_cache": result.from_cache}
            wikitext = None
            revision_id = None
            fetch_status = "error"
            if result.ok:
                data = result.json() or {}
                parsed = data.get("parse", {}) or {}
                wikitext = parsed.get("wikitext", "") or ""
                revision_id = parsed.get("revid")
                fetch_status = "ok" if wikitext else "missing"
                stats.content_fetched += 1
            else:
                raw_payload["http_status"] = result.http_status
                stats.content_failed += 1
            sha = hashlib.sha256(wikitext.encode()).hexdigest() if wikitext else None
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO wg_wikipedia_page_content_cache (
                            wikipedia_title,
                            wikitext,
                            upstream_revision,
                            content_sha256,
                            fetch_status,
                            last_fetched_at,
                            raw_payload
                        )
                        VALUES (
                            :title,
                            :wikitext,
                            :revision,
                            :sha,
                            :fetch_status,
                            now(),
                            CAST(:raw_payload AS jsonb)
                        )
                        ON CONFLICT (wikipedia_title) DO UPDATE SET
                            wikitext = EXCLUDED.wikitext,
                            upstream_revision = EXCLUDED.upstream_revision,
                            content_sha256 = EXCLUDED.content_sha256,
                            fetch_status = EXCLUDED.fetch_status,
                            last_fetched_at = now(),
                            raw_payload = EXCLUDED.raw_payload
                    """),
                    {
                        "title": title,
                        "wikitext": wikitext,
                        "revision": revision_id,
                        "sha": sha,
                        "fetch_status": fetch_status,
                        "raw_payload": json.dumps(raw_payload, sort_keys=True),
                    },
                )
    finally:
        await fetcher.aclose()
    return stats


def _merge_evidence(items: list[AffinityEvidence]) -> tuple[float, float, str, dict[str, int], list[dict[str, Any]]]:
    distribution = Counter(item.source for item in items)
    score = max(item.score for item in items)
    confidence = max(item.confidence for item in items)
    if len(distribution) >= 2:
        score = min(1.0, score + 0.08)
        confidence = min(1.0, confidence + 0.06)
    if all(item.source == "wikipedia_content_mention" for item in items):
        review_status = "needs_review"
    else:
        review_status = "auto"
    evidence = [
        {
            "source": item.source,
            "score": round(item.score, 4),
            "confidence": round(item.confidence, 4),
            "text": item.text[:500],
            **({"payload": item.payload} if item.payload else {}),
        }
        for item in sorted(items, key=lambda item: (-item.score, item.source))[:12]
    ]
    return score, confidence, review_status, dict(distribution), evidence


def _heuristic_evidence(
    *,
    genre: dict[str, Any],
    country: CountryRegion,
    categories: list[str],
    origins: list[str],
    content: str,
) -> list[AffinityEvidence]:
    evidence: list[AffinityEvidence] = []
    title = genre["wikipedia_title"]
    if title_is_region_specific(
        genre_title=title,
        region_name=country.canonical_name,
        region_page_title=country.promoted_title or country.wikipedia_title,
    ):
        evidence.append(
            AffinityEvidence(
                source="title_region_hint",
                score=0.78,
                confidence=0.74,
                text=f"Title contains country or demonym signal for {country.canonical_name}.",
            )
        )

    cat_text = " ".join(categories)
    if cat_text and _alias_count(_norm(cat_text), country.aliases):
        evidence.append(
            AffinityEvidence(
                source="category_region_hint",
                score=0.66,
                confidence=0.62,
                text=f"Category text mentions {country.canonical_name}.",
            )
        )

    origin_text = " ".join(origins)
    if origin_text and _alias_count(_norm(origin_text), country.aliases):
        evidence.append(
            AffinityEvidence(
                source="origin_region_hint",
                score=0.72,
                confidence=0.7,
                text=f"Origin metadata mentions {country.canonical_name}.",
            )
        )

    if content:
        text_norm = _norm(content)
        mention_count = _alias_count(text_norm, country.aliases)
        if mention_count >= 2:
            origin_context = bool(
                re.search(
                    r"\b(originated|emerged|developed|formed|scene|from|based in|popular in)\b",
                    text_norm,
                )
            )
            evidence.append(
                AffinityEvidence(
                    source="wikipedia_content_mention",
                    score=0.62 if origin_context else 0.54,
                    confidence=0.58 if origin_context else 0.5,
                    text=f"Cached Wikipedia content mentions {country.canonical_name} {mention_count} times.",
                    payload={"mention_count": mention_count, "origin_context": origin_context},
                )
            )
    return evidence


async def index_country_affinities(
    *,
    dry_run: bool = False,
    fetch_missing_content: bool = False,
    from_cache: bool = False,
    limit: int | None = None,
    min_score: float = 0.55,
    min_confidence: float = 0.5,
    sample_size: int = 25,
) -> CountryAffinityStats:
    """Interpret all genres against country regions and persist affinity rows."""
    await apply_migrations()
    engine = get_engine()
    stats = CountryAffinityStats(dry_run=dry_run)
    async with engine.connect() as conn:
        countries = await _load_countries(conn)
        genres = await _load_genres(conn, limit=limit)
        categories = await _load_grouped_text(conn, "wg_categories", "category")
        origins = await _load_grouped_text(conn, "wg_origins", "value")
        region_to_countries = await _load_region_country_map(conn)
        evidence_by_key = await _load_existing_relationship_evidence(
            conn, region_to_countries=region_to_countries
        )
        for key, items in (await _load_promoted_child_evidence(conn)).items():
            evidence_by_key[key].extend(items)

    stats.countries_seen = len(countries)
    stats.genres_seen = len(genres)
    if fetch_missing_content:
        cache_stats = await ensure_wikipedia_page_content_cache(
            titles=[genre["wikipedia_title"] for genre in genres],
            from_cache=from_cache,
        )
        stats.content_cached = cache_stats.content_cached
        stats.content_fetched = cache_stats.content_fetched
        stats.content_failed = cache_stats.content_failed

    async with engine.connect() as conn:
        content_cache = await _load_content_cache(conn)

    country_by_id = {country.region_id: country for country in countries}
    genre_by_id = {genre["id"]: genre for genre in genres}
    country_alias_token_index: dict[str, set[str]] = defaultdict(set)
    for country in countries:
        for alias in country.aliases:
            for token in _tokens(alias):
                if len(token) >= 3 or token in {"us", "uk"}:
                    country_alias_token_index[token].add(country.region_id)
    evidence_country_ids_by_genre: dict[str, set[str]] = defaultdict(set)
    for genre_id, country_id in evidence_by_key:
        evidence_country_ids_by_genre[genre_id].add(country_id)
    for genre in genres:
        categories_for_genre = categories.get(genre["id"], [])
        origins_for_genre = origins.get(genre["id"], [])
        genre_content = "\n".join(
            part
            for part in (
                genre.get("summary") or "",
                _plain_wikitext(content_cache.get(genre["wikipedia_title"])),
            )
            if part
        )
        candidate_country_ids = set(evidence_country_ids_by_genre.get(genre["id"], set()))
        candidate_text = " ".join(
            [
                genre["wikipedia_title"],
                genre.get("summary") or "",
                " ".join(categories_for_genre),
                " ".join(origins_for_genre),
                genre_content,
            ]
        )
        for token in _tokens(candidate_text):
            candidate_country_ids.update(country_alias_token_index.get(token, set()))
        for country_id in candidate_country_ids:
            country = country_by_id.get(country_id)
            if not country:
                continue
            key = (genre["id"], country.region_id)
            evidence = list(evidence_by_key.get(key, []))
            evidence.extend(
                _heuristic_evidence(
                    genre=genre,
                    country=country,
                    categories=categories_for_genre,
                    origins=origins_for_genre,
                    content=genre_content,
                )
            )
            if not evidence:
                continue
            score, confidence, review_status, distribution, evidence_payload = _merge_evidence(evidence)
            if score < min_score or confidence < min_confidence:
                continue
            evidence_by_key[key] = [
                AffinityEvidence(
                    source="__merged__",
                    score=score,
                    confidence=confidence,
                    text=review_status,
                    payload={
                        "source_distribution": distribution,
                        "evidence": evidence_payload,
                    },
                )
            ]

    rows: list[dict[str, Any]] = []
    source_distribution: Counter[str] = Counter()
    for (genre_id, region_id), items in evidence_by_key.items():
        if not items or items[0].source != "__merged__":
            continue
        merged = items[0]
        source_distribution.update(merged.payload["source_distribution"])
        row = {
            "genre_id": genre_id,
            "region_id": region_id,
            "score": round(merged.score, 4),
            "confidence": round(merged.confidence, 4),
            "review_status": merged.text,
            "source_distribution": json.dumps(merged.payload["source_distribution"], sort_keys=True),
            "evidence": json.dumps(merged.payload["evidence"], sort_keys=True),
        }
        rows.append(row)
        if len(stats.sample) < sample_size:
            country = country_by_id.get(region_id)
            genre = genre_by_id.get(genre_id)
            stats.sample.append(
                f"{country.canonical_name if country else region_id}: "
                f"{genre['wikipedia_title'] if genre else genre_id} "
                f"score={row['score']} confidence={row['confidence']}"
            )

    stats.affinities_written = len(rows)
    stats.source_distribution = dict(source_distribution)
    if dry_run:
        return stats

    async with engine.begin() as conn:
        deleted = await conn.execute(text("DELETE FROM wg_genre_country_affinities"))
        stats.deleted_existing = int(deleted.rowcount or 0)
        if rows:
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_country_affinities (
                        genre_id,
                        region_id,
                        score,
                        confidence,
                        source_distribution,
                        evidence,
                        review_status,
                        indexed_at
                    )
                    VALUES (
                        :genre_id,
                        :region_id,
                        :score,
                        :confidence,
                        CAST(:source_distribution AS jsonb),
                        CAST(:evidence AS jsonb),
                        :review_status,
                        now()
                    )
                """),
                rows,
            )
    logger.info(
        "country_affinity_index_complete",
        genres=stats.genres_seen,
        countries=stats.countries_seen,
        affinities=stats.affinities_written,
        dry_run=dry_run,
    )
    return stats


async def country_affinity_report(*, region_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    await apply_migrations()
    engine = get_engine()
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                        WITH filtered AS (
                            SELECT a.*
                            FROM wg_genre_country_affinities a
                            WHERE (
                                CAST(:region_id AS text) IS NULL
                                OR a.region_id = CAST(:region_id AS text)
                            )
                        ),
                        country_counts AS (
                            SELECT
                                r.id AS region_id,
                                r.canonical_name,
                                count(*) AS affinities,
                                count(*) FILTER (
                                    WHERE f.review_status = 'needs_review'
                                ) AS needs_review
                            FROM filtered f
                            JOIN wg_regions r ON r.id = f.region_id
                            GROUP BY r.id, r.canonical_name
                        ),
                        source_counts AS (
                            SELECT
                                f.region_id,
                                src.key,
                                sum(src.value::integer) AS value
                            FROM filtered f
                            LEFT JOIN LATERAL jsonb_each_text(f.source_distribution) src ON true
                            WHERE src.key IS NOT NULL
                            GROUP BY f.region_id, src.key
                        ),
                        source_json AS (
                            SELECT
                                region_id,
                                jsonb_object_agg(key, value ORDER BY key) AS sources
                            FROM source_counts
                            GROUP BY region_id
                        )
                        SELECT
                            c.region_id,
                            c.canonical_name,
                            c.affinities,
                            c.needs_review,
                            coalesce(s.sources, '{}'::jsonb) AS sources
                        FROM country_counts c
                        LEFT JOIN source_json s ON s.region_id = c.region_id
                        ORDER BY c.affinities DESC, c.canonical_name
                        LIMIT :limit_value
                    """),
                    {"region_id": region_id, "limit_value": limit},
                )
            )
            .mappings()
            .fetchall()
        )
    return [dict(row) for row in rows]
