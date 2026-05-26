"""Regional ownership classifier v2 (evidence-first + variant discovery).

This pipeline is intentionally conservative: it upgrades region->genre ownership
only on strong evidence, and otherwise stages missing regional-variant candidates
without polluting wg_edges until explicitly promoted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import structlog
from sqlalchemy import text

from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_ownership import (
    BROAD_STYLE_TITLES,
    DEMONYM_OVERRIDES,
    OWNERSHIP_RELATIONS,
    STYLE_MENTION_RELATION,
    title_is_region_specific,
)

logger = structlog.get_logger(__name__)

REVIEW_MODEL = "deterministic-region-ownership-v2"

ARTICLE_SOURCE_TYPE = "wikipedia_article"
CATEGORY_SOURCE_TYPE = "wikipedia_category"
NAVBOX_SOURCE_TYPE = "wikipedia_navbox"

INFERRED_TABLE = "wg_region_inferred_genres"
REGION_HIERARCHY_RELATIONS = {
    "part_of",
    "admin_parent",
    "cultural_region_of",
    "diaspora_region_of",
    "historical_region_of",
    "language_region_of",
}
MAJORITY_IN_SCOPE_SHARE = 0.5
MIN_IN_SCOPE_MENTIONS = 2
MIN_TOTAL_REGION_MENTIONS = 2
_ALIAS_INDEX_CACHE: dict[
    int,
    tuple[dict[int, dict[tuple[str, ...], set[str]]], int],
] = {}


@dataclass(frozen=True)
class OwnershipV2Decision:
    ownership_class: str
    relation: str
    status: str
    reason: str


@dataclass
class RegionOwnershipV2Stats:
    rows_seen: int = 0
    rows_updated: int = 0
    owned_regional_genre: int = 0
    regional_style_mention: int = 0
    inferred_candidate: int = 0
    rejected: int = 0
    needs_review: int = 0
    wikipedia_searches: int = 0
    wikipedia_hits: int = 0
    sample: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegionMentionScore:
    in_scope_mentions: int
    out_scope_mentions: int
    in_scope_share: float
    matched_in_scope: dict[str, int]
    matched_out_scope: dict[str, int]

    @property
    def has_majority(self) -> bool:
        total = self.in_scope_mentions + self.out_scope_mentions
        return (
            self.in_scope_mentions >= MIN_IN_SCOPE_MENTIONS
            and total >= MIN_TOTAL_REGION_MENTIONS
            and self.in_scope_share > MAJORITY_IN_SCOPE_SHARE
        )


@dataclass(frozen=True)
class RegionMentionContext:
    variants_by_id: dict[str, set[str]]
    names_by_id: dict[str, str]
    parent_ids_by_region: dict[str, list[str]]
    descendant_ids_by_region: dict[str, list[str]]


def _normalize(value: str | None) -> str:
    return " ".join((value or "").replace("_", " ").casefold().split())


def _normalize_mention(value: str | None) -> str:
    value = (value or "").casefold().replace("&", " and ")
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[-‐‑‒–—/]", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(value))


def _mention_tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_mention(value))


def _strip_region_music_prefix(title: str | None) -> str:
    lower = _normalize(title)
    for prefix in (
        "music of the ",
        "music of ",
        "music in the ",
        "music in ",
        "traditional music of the ",
        "traditional music of ",
    ):
        if lower.startswith(prefix):
            return lower.removeprefix(prefix)
    if lower.endswith(" music") and len(lower) > len(" music"):
        return lower.removesuffix(" music")
    return lower


def _without_parenthetical(value: str | None) -> str:
    return re.sub(r"\s*\([^)]*\)", "", value or "").strip()


def _demonym_candidates(region_name: str) -> list[str]:
    region = _normalize(region_name)
    if not region:
        return []
    # Prefer explicit demonyms only; suffix heuristics generate too many false forms
    # (e.g. "ghanan", "thaiish") and create noisy Wikipedia search queries.
    candidates = list(DEMONYM_OVERRIDES.get(region, set()))
    # Prefer stable order + dedupe.
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        item_n = _normalize(item)
        if not item_n or item_n in seen:
            continue
        out.append(item_n)
        seen.add(item_n)
    return out


def _candidate_variant_queries(*, region_name: str, base_genre_title: str) -> list[str]:
    genre = _normalize(base_genre_title)
    if not genre:
        return []
    out: list[str] = []
    region = _normalize(region_name)
    for demonym in _demonym_candidates(region_name):
        out.append(f"{demonym} {genre}")
        if not genre.endswith("music"):
            out.append(f"{demonym} {genre} music")
    if region:
        out.append(f"{genre} in {region}")
        out.append(f"{genre} of {region}")
    # De-dupe preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item in seen:
            continue
        unique.append(item)
        seen.add(item)
    return unique


def _wikipedia_hit_is_plausible_variant(*, hit_title: str, query: str, genre_title: str) -> bool:
    title = _normalize(hit_title)
    q = _normalize(query)
    if not title or not q:
        return False
    if title.startswith(("music of ", "list of ", "category:")):
        return False
    # Prefer exact match first.
    if title == q:
        return True
    # Otherwise require both a demonym/region token and the base genre token(s).
    q_tokens = _tokens(q)
    genre_tokens = _tokens(_normalize(genre_title))
    if not q_tokens or not genre_tokens:
        return False
    # The query is typically "{demonym} {genre...}" so require at least one
    # non-genre token (demonym) plus all genre tokens.
    non_genre = [t for t in q_tokens if t not in genre_tokens]
    if not non_genre:
        return False
    if not any(re.search(rf"\b{re.escape(t)}\b", title) for t in non_genre):
        return False
    return all(re.search(rf"\b{re.escape(t)}\b", title) for t in genre_tokens)


def _is_genre_like_section(section: str | None) -> bool:
    lower = _normalize(section)
    if not lower:
        return False
    return any(
        term in lower
        for term in (
            "classical",
            "dance",
            "folk",
            "genre",
            "genres",
            "indigenous",
            "local",
            "popular",
            "regional",
            "scene",
            "style",
            "styles",
            "tradition",
            "traditions",
            "traditional",
        )
    )


def _is_broad_style_title(title: str | None) -> bool:
    return _normalize(title) in BROAD_STYLE_TITLES


def _compile_region_variants(
    *,
    canonical_name: str | None,
    display_title: str | None,
    wikipedia_title: str | None,
) -> set[str]:
    out: set[str] = set()
    bases = {
        _normalize(canonical_name),
        _normalize(display_title),
        _normalize(wikipedia_title),
        _strip_region_music_prefix(wikipedia_title),
        _normalize(_without_parenthetical(canonical_name)),
        _normalize(_without_parenthetical(display_title)),
        _normalize(_without_parenthetical(_strip_region_music_prefix(wikipedia_title))),
    }
    for base in list(bases):
        if base:
            bases.add(_without_parenthetical(base))
            bases.update(DEMONYM_OVERRIDES.get(base, set()))

    for item in bases:
        norm = _normalize_mention(item)
        if not norm:
            continue
        toks = _mention_tokens(norm)
        if not toks:
            continue
        if len(toks) == 1 and len(toks[0]) < 4:
            continue
        if norm == "us":
            continue
        out.add(norm)
    return out


def _alias_mention_spans(text_norm: str, alias: str) -> list[tuple[int, int]]:
    if not text_norm or not alias:
        return []
    return [
        match.span(1)
        for match in re.finditer(rf"(?:^| )({re.escape(alias)})(?: |$)", text_norm)
    ]


def _count_region_alias_mentions(text_norm: str, aliases: set[str]) -> int:
    spans: list[tuple[int, int]] = []
    for alias in aliases:
        spans.extend(_alias_mention_spans(text_norm, alias))
    if not spans:
        return 0

    # Count distinct alias hits while avoiding overlap between aliases like
    # "united states" and a shorter form that could sit inside the same span.
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    accepted: list[tuple[int, int]] = []
    for start, end in spans:
        if any(not (end <= prev_start or start >= prev_end) for prev_start, prev_end in accepted):
            continue
        accepted.append((start, end))
    return len(accepted)


def _get_region_alias_index(
    context: RegionMentionContext,
) -> tuple[dict[int, dict[tuple[str, ...], set[str]]], int]:
    cache_key = id(context)
    cached = _ALIAS_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    by_length: dict[int, dict[tuple[str, ...], set[str]]] = {}
    max_len = 0
    for region_id, aliases in context.variants_by_id.items():
        for alias in aliases:
            tokens = tuple(_mention_tokens(alias))
            if not tokens:
                continue
            max_len = max(max_len, len(tokens))
            by_length.setdefault(len(tokens), {}).setdefault(tokens, set()).add(region_id)
    indexed = (by_length, max_len)
    _ALIAS_INDEX_CACHE[cache_key] = indexed
    return indexed


def _count_all_region_mentions(
    *,
    text_value: str,
    context: RegionMentionContext,
) -> dict[str, int]:
    tokens = _mention_tokens(text_value)
    if not tokens:
        return {}
    alias_by_length, max_alias_len = _get_region_alias_index(context)
    if not alias_by_length or max_alias_len <= 0:
        return {}

    counts: dict[str, int] = {}
    occupied_until = 0
    token_count = len(tokens)
    for idx in range(token_count):
        if idx < occupied_until:
            continue
        max_len_here = min(max_alias_len, token_count - idx)
        for length in range(max_len_here, 0, -1):
            aliases = alias_by_length.get(length)
            if not aliases:
                continue
            matched_region_ids = aliases.get(tuple(tokens[idx : idx + length]))
            if not matched_region_ids:
                continue
            for candidate_region_id in matched_region_ids:
                counts[candidate_region_id] = counts.get(candidate_region_id, 0) + 1
            occupied_until = idx + length
            break
    return counts


def _score_region_mention_counts(
    *,
    mention_counts_by_region: dict[str, int],
    region_id: str,
    context: RegionMentionContext,
) -> RegionMentionScore:
    in_scope_ids = {
        region_id,
        *context.parent_ids_by_region.get(region_id, []),
        *context.descendant_ids_by_region.get(region_id, []),
    }
    matched_in: dict[str, int] = {}
    matched_out: dict[str, int] = {}

    for candidate_region_id, count in mention_counts_by_region.items():
        if count <= 0:
            continue
        name = context.names_by_id.get(candidate_region_id, candidate_region_id)
        if candidate_region_id in in_scope_ids:
            matched_in[name] = matched_in.get(name, 0) + count
        else:
            matched_out[name] = matched_out.get(name, 0) + count

    in_scope = sum(matched_in.values())
    out_scope = sum(matched_out.values())
    total = in_scope + out_scope
    share = in_scope / total if total else 0.0
    return RegionMentionScore(
        in_scope_mentions=in_scope,
        out_scope_mentions=out_scope,
        in_scope_share=share,
        matched_in_scope=dict(sorted(matched_in.items(), key=lambda item: (-item[1], item[0]))[:8]),
        matched_out_scope=dict(sorted(matched_out.items(), key=lambda item: (-item[1], item[0]))[:8]),
    )


async def _load_region_mention_context(conn) -> RegionMentionContext:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT id, canonical_name, display_title, wikipedia_title
                    FROM wg_regions
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    by_region: dict[str, set[str]] = {}
    names_by_id: dict[str, str] = {}
    for row in rows:
        rid = str(row["id"])
        names_by_id[rid] = str(row["canonical_name"])
        by_region[rid] = _compile_region_variants(
            canonical_name=row["canonical_name"],
            display_title=row["display_title"],
            wikipedia_title=row["wikipedia_title"],
        )

    rel_rows = (
        (
            await conn.execute(
                text("""
                    SELECT from_region_id, to_region_id, relation
                    FROM wg_region_relationships
                    WHERE status = 'accepted'
                      AND relation = ANY(:relations)
                """),
                {"relations": sorted(REGION_HIERARCHY_RELATIONS)},
            )
        )
        .mappings()
        .fetchall()
    )
    parents_by_child: dict[str, list[str]] = {}
    children_by_parent: dict[str, list[str]] = {}
    for row in rel_rows:
        child = str(row["from_region_id"])
        parent = str(row["to_region_id"])
        parents_by_child.setdefault(child, []).append(parent)
        children_by_parent.setdefault(parent, []).append(child)

    def closure(start: str, adjacency: dict[str, list[str]]) -> list[str]:
        seen: set[str] = set()
        queue = list(adjacency.get(start, []))
        out: list[str] = []
        while queue:
            next_id = queue.pop(0)
            if next_id in seen:
                continue
            seen.add(next_id)
            out.append(next_id)
            queue.extend(adjacency.get(next_id, []))
        return out

    all_ids = set(by_region.keys())
    parent_closure = {rid: closure(rid, parents_by_child) for rid in all_ids}
    descendant_closure = {rid: closure(rid, children_by_parent) for rid in all_ids}
    return RegionMentionContext(
        variants_by_id=by_region,
        names_by_id=names_by_id,
        parent_ids_by_region=parent_closure,
        descendant_ids_by_region=descendant_closure,
    )


def _score_region_mentions(
    *,
    text_value: str,
    region_id: str,
    context: RegionMentionContext,
) -> RegionMentionScore:
    mention_counts_by_region = _count_all_region_mentions(text_value=text_value, context=context)
    if not mention_counts_by_region:
        return RegionMentionScore(0, 0, 0.0, {}, {})
    return _score_region_mention_counts(
        mention_counts_by_region=mention_counts_by_region,
        region_id=region_id,
        context=context,
    )


async def _load_genre_scoring_text(
    *,
    fetcher: WikiFetcher,
    genre_title: str,
    genre_summary: str,
    wikitext_cache: dict[str, str] | None,
) -> str:
    summary = str(genre_summary or "")
    if not genre_title:
        return summary

    if wikitext_cache is not None and genre_title in wikitext_cache:
        return f"{summary}\n{wikitext_cache[genre_title]}".strip()

    plain = ""
    try:
        result = await fetcher.fetch_wikitext(genre_title)
        if result.ok:
            data = result.json() or {}
            wikitext = (data.get("parse", {}) or {}).get("wikitext", "") or ""
            # Pull enough lead/section text to count region distribution, while
            # avoiding very long list pages dominating classification latency.
            plain = re.sub(r"\{\{[^{}]*\}\}", " ", str(wikitext))
            plain = re.sub(r"<ref[^>]*>.*?</ref>", " ", plain, flags=re.IGNORECASE | re.DOTALL)
            plain = re.sub(r"<[^>]+>", " ", plain)
            plain = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\1 \2", plain)
            plain = re.sub(r"\[\[([^]]+)\]\]", r"\1", plain)
            plain = re.sub(r"'{2,}", "", plain)
            plain = plain[:25000]
    except Exception:
        plain = ""

    if wikitext_cache is not None:
        wikitext_cache[genre_title] = plain
    return f"{summary}\n{plain}".strip()


async def _has_category_ownership(
    conn,
    *,
    region_ids: list[str],
    genre_id: str,
) -> bool:
    if not region_ids:
        return False
    found = await conn.scalar(
        text("""
            SELECT 1
            FROM wg_region_genre_relationships rel
            WHERE rel.status = 'accepted'
              AND rel.source_type = :source_type
              AND rel.region_id = ANY(:region_ids)
              AND rel.genre_id = :genre_id
            LIMIT 1
        """),
        {"source_type": CATEGORY_SOURCE_TYPE, "region_ids": region_ids, "genre_id": genre_id},
    )
    return bool(found)


async def _search_local_genre_variants(
    conn,
    *,
    query: str,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    q_norm = _normalize_mention(q)
    # Prefer exact / near-exact title or alias hits.
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT g.id AS genre_id, g.wikipedia_title AS title, 'title' AS hit_kind
                    FROM wg_genres g
                    WHERE lower(g.wikipedia_title) = lower(:q)
                       OR btrim(regexp_replace(regexp_replace(lower(g.wikipedia_title), '[^a-z0-9]+', ' ', 'g'), '[[:space:]]+', ' ', 'g')) = :q_norm
                    UNION ALL
                    SELECT a.genre_id AS genre_id, a.alias AS title, 'alias' AS hit_kind
                    FROM wg_aliases a
                    WHERE lower(a.alias) = lower(:q)
                       OR btrim(regexp_replace(regexp_replace(lower(a.alias), '[^a-z0-9]+', ' ', 'g'), '[[:space:]]+', ' ', 'g')) = :q_norm
                    UNION ALL
                    SELECT r.to_genre_id AS genre_id, r.from_title AS title, 'redirect' AS hit_kind
                    FROM wg_redirects r
                    WHERE lower(r.from_title) = lower(:q)
                       OR btrim(regexp_replace(regexp_replace(lower(r.from_title), '[^a-z0-9]+', ' ', 'g'), '[[:space:]]+', ' ', 'g')) = :q_norm
                    LIMIT 10
                """),
                {"q": q, "q_norm": q_norm},
            )
        )
        .mappings()
        .fetchall()
    )
    return [dict(r) for r in rows]


async def _upsert_inferred_candidate(
    conn,
    *,
    region_id: str,
    base_genre_id: str,
    candidate_kind: str,
    proposed_display_title: str,
    wikipedia_title: str | None,
    source_title: str | None,
    source_section: str | None,
    confidence: float,
    raw_payload: dict[str, Any],
) -> None:
    await conn.execute(
        text(f"""
            INSERT INTO {INFERRED_TABLE} (
                region_id,
                base_genre_id,
                candidate_kind,
                proposed_display_title,
                wikipedia_title,
                source_title,
                source_section,
                confidence,
                status,
                raw_payload,
                updated_at
            )
            VALUES (
                :region_id,
                :base_genre_id,
                :candidate_kind,
                :proposed_display_title,
                :wikipedia_title,
                :source_title,
                :source_section,
                :confidence,
                'proposed',
                :raw_payload,
                now()
            )
            ON CONFLICT (
                region_id,
                base_genre_id,
                candidate_kind,
                coalesce(wikipedia_title, ''),
                coalesce(source_title, ''),
                coalesce(source_section, '')
            )
            DO UPDATE
            SET proposed_display_title = excluded.proposed_display_title,
                confidence = greatest({INFERRED_TABLE}.confidence, excluded.confidence),
                raw_payload = {INFERRED_TABLE}.raw_payload || excluded.raw_payload,
                updated_at = now()
        """),
        {
            "region_id": region_id,
            "base_genre_id": base_genre_id,
            "candidate_kind": candidate_kind,
            "proposed_display_title": proposed_display_title,
            "wikipedia_title": wikipedia_title,
            "source_title": source_title,
            "source_section": source_section,
            "confidence": confidence,
            "raw_payload": json.dumps(raw_payload),
        },
    )


async def _upsert_existing_variant_relationship(
    conn,
    *,
    source_row: dict[str, Any],
    hit: dict[str, Any],
    reason: str,
) -> None:
    variant_genre_id = hit.get("genre_id")
    if not variant_genre_id or variant_genre_id == source_row["genre_id"]:
        return
    relation = source_row["relation"] if source_row["relation"] in OWNERSHIP_RELATIONS else "regional_scene"
    await conn.execute(
        text("""
            INSERT INTO wg_region_genre_relationships (
                region_id,
                genre_id,
                relation,
                source_id,
                source_type,
                source_url,
                source_title,
                source_section,
                evidence_text,
                confidence,
                status,
                raw_payload,
                review_reason,
                reviewer_model,
                updated_at
            )
            VALUES (
                :region_id,
                :genre_id,
                :relation,
                :source_id,
                :source_type,
                :source_url,
                :source_title,
                :source_section,
                :evidence_text,
                :confidence,
                'accepted',
                :raw_payload,
                :review_reason,
                :reviewer_model,
                now()
            )
            ON CONFLICT (
                region_id,
                genre_id,
                relation,
                source_type,
                coalesce(source_url, ''),
                coalesce(source_title, ''),
                coalesce(source_section, '')
            )
            DO UPDATE
            SET status = 'accepted',
                confidence = greatest(wg_region_genre_relationships.confidence, excluded.confidence),
                raw_payload = wg_region_genre_relationships.raw_payload || excluded.raw_payload,
                review_reason = excluded.review_reason,
                reviewer_model = excluded.reviewer_model,
                updated_at = now()
        """),
        {
            "region_id": source_row["region_id"],
            "genre_id": variant_genre_id,
            "relation": relation,
            "source_id": source_row.get("source_id"),
            "source_type": source_row["source_type"],
            "source_url": source_row.get("source_url"),
            "source_title": source_row.get("source_title"),
            "source_section": source_row.get("source_section"),
            "evidence_text": (
                f"Resolved regional variant {hit.get('title')} from base target "
                f"{source_row.get('genre_title')}."
            ),
            "confidence": float(source_row.get("confidence") or 0.5),
            "raw_payload": json.dumps(
                {
                    "variant_resolution": {
                        "base_genre_id": source_row["genre_id"],
                        "base_genre_title": source_row.get("genre_title"),
                        "hit_title": hit.get("title"),
                        "hit_kind": hit.get("hit_kind"),
                        "reason": reason,
                    },
                    "reviewer_model": REVIEW_MODEL,
                }
            ),
            "review_reason": reason,
            "reviewer_model": REVIEW_MODEL,
        },
    )


async def _style_mention_with_optional_variant(
    conn,
    *,
    fetcher: WikiFetcher,
    region_name: str,
    genre_title: str,
    source_title: str | None,
    source_section: str | None,
    evidence_text: str | None,
    search_cache: dict[str, dict[str, Any] | None] | None,
    reason: str,
    status: str = "accepted",
    enable_wikipedia_search: bool = False,
) -> tuple[OwnershipV2Decision, dict[str, Any] | None]:
    should_stage_variant = (
        _is_genre_like_section(source_section)
        or _is_broad_style_title(genre_title)
        or bool(evidence_text and any(query in _normalize(evidence_text) for query in ("linked from template", "linked from category")))
    )
    if should_stage_variant:
        for query in _candidate_variant_queries(region_name=region_name, base_genre_title=genre_title):
            if search_cache is not None and query in search_cache:
                cached = search_cache[query]
                if cached:
                    return (
                        OwnershipV2Decision(
                            ownership_class="regional_style_mention",
                            relation=STYLE_MENTION_RELATION,
                            status=status,
                            reason=cached.get("reason") or reason,
                        ),
                        cached.get("inferred"),
                    )
                continue

            local_hits = await _search_local_genre_variants(conn, query=query)
            if local_hits:
                inferred_payload = {
                    "candidate_kind": "existing_db_hit",
                    "query": query,
                    "hits": local_hits,
                }
                if search_cache is not None:
                    search_cache[query] = {
                        "reason": "Potential missed regional variant exists in local DB.",
                        "inferred": inferred_payload,
                    }
                return (
                    OwnershipV2Decision(
                        ownership_class="regional_style_mention",
                        relation=STYLE_MENTION_RELATION,
                        status=status,
                        reason="Potential missed regional variant exists in local DB.",
                    ),
                    inferred_payload,
                )

            if not enable_wikipedia_search:
                if search_cache is not None:
                    search_cache[query] = None
                continue

            result = await fetcher.search_titles(query, limit=5)
            search_payload = {"query": query, "result_ok": result.ok}
            if result.ok:
                data = result.json() or {}
                hits = (data.get("query", {}) or {}).get("search", []) or []
                best = hits[0] if hits else None
                if best and isinstance(best, dict):
                    title = best.get("title")
                    if title and _wikipedia_hit_is_plausible_variant(
                        hit_title=str(title), query=query, genre_title=genre_title
                    ):
                        proposed = str(title)
                        inferred_payload = {
                            "candidate_kind": "wikipedia_page",
                            "wikipedia_title": proposed,
                            "proposed_display_title": proposed,
                            "search": search_payload,
                        }
                        if search_cache is not None:
                            search_cache[query] = {
                                "reason": "Potential missed regional variant candidate found on Wikipedia.",
                                "inferred": inferred_payload,
                            }
                        return (
                            OwnershipV2Decision(
                                ownership_class="regional_style_mention",
                                relation=STYLE_MENTION_RELATION,
                                status=status,
                                reason="Potential missed regional variant candidate found on Wikipedia.",
                            ),
                            inferred_payload,
                        )

            if search_cache is not None:
                search_cache[query] = None

        demonyms = _demonym_candidates(region_name)
        proposed = f"{(demonyms[0] if demonyms else _normalize(region_name))} {_normalize(genre_title)}".strip()
        proposed_display = proposed.title() if proposed else f"{region_name} {genre_title}"
        return (
            OwnershipV2Decision(
                ownership_class="regional_style_mention",
                relation=STYLE_MENTION_RELATION,
                status=status,
                reason="Broad genre section exists but lacks subgenre links; stage inferred variant candidate.",
            ),
            {
                "candidate_kind": "section_inferred",
                "proposed_display_title": proposed_display,
                "source_title": source_title,
                "source_section": source_section,
            },
        )

    return (
        OwnershipV2Decision(
            ownership_class="regional_style_mention",
            relation=STYLE_MENTION_RELATION,
            status=status,
            reason=reason,
        ),
        None,
    )


async def classify_region_genre_ownership_v2(
    *,
    row: dict[str, Any],
    conn,
    fetcher: WikiFetcher,
    mention_context: RegionMentionContext,
    search_cache: dict[str, dict[str, Any] | None] | None = None,
    wikitext_cache: dict[str, str] | None = None,
    mention_counts_cache: dict[str, dict[str, int]] | None = None,
    enable_wikipedia_search: bool = False,
) -> tuple[OwnershipV2Decision, dict[str, Any] | None]:
    """Return (decision, inferred_candidate_payload?)."""
    region_id = str(row["region_id"])
    genre_id = str(row["genre_id"])
    region_name = str(row["region_name"] or "")
    region_page_title = row.get("region_wikipedia_title") or row.get("region_page_title")
    genre_title = str(row["genre_title"] or "")
    genre_summary = row.get("genre_summary") or ""
    source_title = row.get("source_title")
    source_section = row.get("source_section")
    source_type = str(row.get("source_type") or "")
    evidence_kind = _normalize(row.get("evidence_kind"))
    evidence_text = row.get("evidence_text")
    current_relation = str(row.get("relation") or "regional_scene")
    genre_lower = _normalize(genre_title)
    source_title_lower = _normalize(str(source_title or ""))

    # Guard against list/category artifacts becoming graph-owned.
    if genre_lower.startswith(("list of ", "lists of ", "category:")):
        return (
            OwnershipV2Decision(
                ownership_class="regional_style_mention",
                relation=STYLE_MENTION_RELATION,
                status="rejected",
                reason="Target is a list/category artifact, not a genre.",
            ),
            None,
        )

    # 1) Title contains region/parent variant => ownership.
    if title_is_region_specific(
        genre_title=genre_title,
        region_name=region_name,
        region_page_title=region_page_title,
    ):
        return (
            OwnershipV2Decision(
                ownership_class="owned_regional_genre",
                relation=current_relation if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
                status="accepted",
                reason="Target title is region-specific.",
            ),
            None,
        )

    scoring_text = await _load_genre_scoring_text(
        fetcher=fetcher,
        genre_title=genre_title,
        genre_summary=genre_summary,
        wikitext_cache=wikitext_cache,
    )
    if mention_counts_cache is not None and genre_id in mention_counts_cache:
        mention_counts = mention_counts_cache[genre_id]
    else:
        mention_counts = _count_all_region_mentions(
            text_value=scoring_text,
            context=mention_context,
        )
        if mention_counts_cache is not None:
            mention_counts_cache[genre_id] = mention_counts
    mention_score = _score_region_mention_counts(
        mention_counts_by_region=mention_counts,
        region_id=region_id,
        context=mention_context,
    )
    score_payload = {
        "region_mention_score": {
            "in_scope_mentions": mention_score.in_scope_mentions,
            "out_scope_mentions": mention_score.out_scope_mentions,
            "in_scope_share": round(mention_score.in_scope_share, 4),
            "matched_in_scope": mention_score.matched_in_scope,
            "matched_out_scope": mention_score.matched_out_scope,
            "majority_threshold": MAJORITY_IN_SCOPE_SHARE,
            "min_in_scope_mentions": MIN_IN_SCOPE_MENTIONS,
        }
    }

    # 2) Non-region-specific targets must be mostly about this region, its
    # ancestors/superregions, or descendants/subregions. This is intentionally
    # source-agnostic so templates/lists/categories cannot bypass the ownership
    # majority check for generic base genres.
    if mention_score.has_majority:
        return (
            OwnershipV2Decision(
                ownership_class="owned_regional_genre",
                relation=current_relation if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
                status="accepted",
                reason=(
                    "Genre page region mentions are majority in-scope "
                    f"({mention_score.in_scope_mentions}/"
                    f"{mention_score.in_scope_mentions + mention_score.out_scope_mentions})."
                ),
            ),
            score_payload,
        )

    # 3) Otherwise this is regional context. Try to resolve or stage the
    # regionalized variant while keeping the broad/base target out of the graph.
    decision, inferred = await _style_mention_with_optional_variant(
        conn,
        fetcher=fetcher,
        region_name=region_name,
        genre_title=genre_title,
        source_title=source_title,
        source_section=source_section,
        evidence_text=evidence_text,
        search_cache=search_cache,
        reason=(
            "Genre page region mentions are not majority in-scope "
            f"({mention_score.in_scope_mentions}/"
            f"{mention_score.in_scope_mentions + mention_score.out_scope_mentions}); "
            "treated as regional style context."
        ),
        enable_wikipedia_search=enable_wikipedia_search,
    )
    payload = dict(score_payload)
    if inferred:
        payload["inferred"] = inferred
    return decision, payload


async def classify_existing_region_genre_ownership_v2(*, sample_size: int = 25) -> RegionOwnershipV2Stats:
    """Run v2 classification over existing article-derived region->genre rows."""
    await apply_migrations()
    stats = RegionOwnershipV2Stats()
    engine = get_engine()

    async with engine.begin() as conn:
        # Ensure inferred table exists (migration applies, but table might be absent in tests).
        await conn.execute(text("SELECT 1"))
        # Clear prior proposed candidates so a re-run produces a clean snapshot.
        await conn.execute(text(f"DELETE FROM {INFERRED_TABLE} WHERE status = 'proposed'"))

        mention_context = await _load_region_mention_context(conn)

        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            rel.id,
                            rel.source_id,
                            rel.region_id,
                            region.canonical_name AS region_name,
                            region.wikipedia_title AS region_wikipedia_title,
                            rel.genre_id,
                            genre.wikipedia_title AS genre_title,
                            genre.summary AS genre_summary,
                            rel.relation,
                            rel.confidence,
                            rel.status,
                            rel.source_type,
                            rel.source_url,
                            rel.source_title,
                            rel.source_section,
                            rel.evidence_text,
                            rel.raw_payload ->> 'evidence_kind' AS evidence_kind
                        FROM wg_region_genre_relationships rel
                        JOIN wg_regions region ON region.id = rel.region_id
                        JOIN wg_genres genre ON genre.id = rel.genre_id
                        WHERE rel.status IN ('accepted', 'proposed', 'needs_review')
                        ORDER BY rel.id
                    """),
                )
            )
            .mappings()
            .fetchall()
        )

        fetcher = WikiFetcher(from_cache=False)
        search_cache: dict[str, dict[str, Any] | None] = {}
        wikitext_cache: dict[str, str] = {}
        mention_counts_cache: dict[str, dict[str, int]] = {}
        try:
            stats.rows_seen = len(rows)
            for row in rows:
                row_dict = dict(row)
                decision, inferred = await classify_region_genre_ownership_v2(
                    row=row_dict,
                    conn=conn,
                    fetcher=fetcher,
                    mention_context=mention_context,
                    search_cache=search_cache,
                    wikitext_cache=wikitext_cache,
                    mention_counts_cache=mention_counts_cache,
                )

                if decision.ownership_class == "owned_regional_genre":
                    stats.owned_regional_genre += 1
                elif decision.status == "rejected":
                    stats.rejected += 1
                elif decision.status == "needs_review":
                    stats.needs_review += 1
                else:
                    stats.regional_style_mention += 1

                ownership_payload = {
                    "ownership_review_v2": {
                        "ownership_class": decision.ownership_class,
                        "relation": decision.relation,
                        "status": decision.status,
                        "reason": decision.reason,
                        "reviewer_model": REVIEW_MODEL,
                    }
                }
                inferred_candidate = None
                if inferred:
                    if "region_mention_score" in inferred:
                        ownership_payload["ownership_review_v2"]["region_mention_score"] = inferred[
                            "region_mention_score"
                        ]
                    inferred_candidate = inferred.get("inferred") if "inferred" in inferred else inferred
                    if inferred_candidate and inferred_candidate.get("candidate_kind"):
                        ownership_payload["ownership_review_v2"]["inferred"] = inferred_candidate

                duplicate_id = None
                if decision.relation != row_dict["relation"]:
                    duplicate_id = await conn.scalar(
                        text("""
                            SELECT id
                            FROM wg_region_genre_relationships
                            WHERE id <> :id
                              AND region_id = :region_id
                              AND genre_id = :genre_id
                              AND relation = :relation
                              AND source_type = :source_type
                              AND coalesce(source_url, '') = coalesce(:source_url, '')
                              AND coalesce(source_title, '') = coalesce(:source_title, '')
                              AND coalesce(source_section, '') = coalesce(:source_section, '')
                            LIMIT 1
                        """),
                        {
                            "id": row_dict["id"],
                            "region_id": row_dict["region_id"],
                            "genre_id": row_dict["genre_id"],
                            "relation": decision.relation,
                            "source_type": row_dict["source_type"],
                            "source_url": row_dict["source_url"],
                            "source_title": row_dict["source_title"],
                            "source_section": row_dict["source_section"],
                        },
                    )

                if duplicate_id is not None:
                    await conn.execute(
                        text("""
                            UPDATE wg_region_genre_relationships target
                            SET source_id = coalesce(target.source_id, source.source_id),
                                evidence_text = coalesce(target.evidence_text, source.evidence_text),
                                confidence = greatest(target.confidence, source.confidence),
                                status = :status,
                                review_reason = :review_reason,
                                reviewer_model = :reviewer_model,
                                raw_payload = target.raw_payload || source.raw_payload || :raw_payload,
                                updated_at = now()
                            FROM wg_region_genre_relationships source
                            WHERE target.id = :duplicate_id
                              AND source.id = :id
                        """),
                        {
                            "id": row_dict["id"],
                            "duplicate_id": duplicate_id,
                            "status": decision.status,
                            "review_reason": decision.reason,
                            "reviewer_model": REVIEW_MODEL,
                            "raw_payload": json.dumps(ownership_payload),
                        },
                    )
                    result = await conn.execute(
                        text("DELETE FROM wg_region_genre_relationships WHERE id = :id"),
                        {"id": row_dict["id"]},
                    )
                    stats.rows_updated += result.rowcount or 0
                else:
                    result = await conn.execute(
                        text("""
                            UPDATE wg_region_genre_relationships
                            SET relation = :relation,
                                status = :status,
                                review_reason = :review_reason,
                                reviewer_model = :reviewer_model,
                                raw_payload = raw_payload || :raw_payload,
                                updated_at = now()
                            WHERE id = :id
                        """),
                        {
                            "id": row_dict["id"],
                            "relation": decision.relation,
                            "status": decision.status,
                            "review_reason": decision.reason,
                            "reviewer_model": REVIEW_MODEL,
                            "raw_payload": json.dumps(ownership_payload),
                        },
                    )
                    stats.rows_updated += result.rowcount or 0

                # Materialize inferred candidates into staging table.
                if inferred_candidate and inferred_candidate.get("candidate_kind") == "existing_db_hit":
                    hits = inferred_candidate.get("hits") or []
                    if hits:
                        stats.inferred_candidate += 1
                        await _upsert_existing_variant_relationship(
                            conn,
                            source_row=row_dict,
                            hit=hits[0],
                            reason="Resolved existing regional variant from regionalized base-style evidence.",
                        )
                elif inferred_candidate and inferred_candidate.get("candidate_kind") in {
                    "wikipedia_page",
                    "section_inferred",
                }:
                    stats.inferred_candidate += 1
                    await _upsert_inferred_candidate(
                        conn,
                        region_id=row_dict["region_id"],
                        base_genre_id=row_dict["genre_id"],
                        candidate_kind=inferred_candidate["candidate_kind"],
                        proposed_display_title=inferred_candidate.get("proposed_display_title")
                        or inferred_candidate.get("wikipedia_title")
                        or row_dict["genre_title"],
                        wikipedia_title=inferred_candidate.get("wikipedia_title"),
                        source_title=inferred_candidate.get("source_title") or row_dict.get("source_title"),
                        source_section=inferred_candidate.get("source_section") or row_dict.get("source_section"),
                        confidence=float(row_dict.get("confidence") or 0.5),
                        raw_payload={
                            "reviewer_model": REVIEW_MODEL,
                            "inferred": inferred_candidate,
                        },
                    )

                if len(stats.sample) < sample_size:
                    stats.sample.append(
                        f"{decision.status}:{decision.ownership_class} "
                        f"{row_dict['region_name']} -> {row_dict['genre_title']} ({decision.reason})"
                    )
        finally:
            await fetcher.aclose()

    logger.info(
        "region_ownership_v2_complete",
        rows_seen=stats.rows_seen,
        rows_updated=stats.rows_updated,
        owned_regional_genre=stats.owned_regional_genre,
        regional_style_mention=stats.regional_style_mention,
        inferred_candidate=stats.inferred_candidate,
        rejected=stats.rejected,
        needs_review=stats.needs_review,
    )
    return stats


async def audit_region_variant_coverage(*, sample_size: int = 25) -> dict[str, Any]:
    """Summarize inferred candidates by kind and sample a few."""
    await apply_migrations()
    engine = get_engine()
    out: dict[str, Any] = {"counts": {}, "sample": []}
    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text(f"""
                        SELECT candidate_kind, count(*) AS count
                        FROM {INFERRED_TABLE}
                        GROUP BY candidate_kind
                        ORDER BY count DESC, candidate_kind
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        out["counts"] = {str(r["candidate_kind"]): int(r["count"]) for r in rows}
        sample_rows = (
            (
                await conn.execute(
                    text(f"""
                        SELECT
                            inf.candidate_kind,
                            region.canonical_name AS region_name,
                            base.wikipedia_title AS base_genre,
                            inf.proposed_display_title,
                            inf.wikipedia_title,
                            inf.source_title,
                            inf.source_section
                        FROM {INFERRED_TABLE} inf
                        JOIN wg_regions region ON region.id = inf.region_id
                        JOIN wg_genres base ON base.id = inf.base_genre_id
                        ORDER BY inf.id DESC
                        LIMIT :limit
                    """),
                    {"limit": sample_size},
                )
            )
            .mappings()
            .fetchall()
        )
        out["sample"] = [dict(r) for r in sample_rows]
    return out
