"""Classify whether a regional page link is graph ownership or local context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

REVIEW_MODEL = "deterministic-region-ownership-v1"
STYLE_MENTION_RELATION = "regional_style_mention"
INFLUENCE_RELATION = "influence_or_context"
OWNERSHIP_RELATIONS = {
    "regional_scene",
    "local_scene",
    "traditional_region",
    "indigenous_region",
    "historical_region",
    "diaspora_region",
    "cultural_region",
}

BROAD_STYLE_TITLES = {
    "alternative rock",
    "blues",
    "calypso music",
    "classical music",
    "contemporary music",
    "country music",
    "dance music",
    "electronic music",
    "experimental music",
    "folk music",
    "gospel music",
    "heavy metal music",
    "hip-hop",
    "indigenous music",
    "jazz",
    "opera",
    "pop music",
    "popular music",
    "punk rock",
    "reggae",
    "rhythm and blues",
    "rock and roll",
    "rock music",
    "soca music",
    "world music",
}

ORIGIN_REGION_ALLOWLIST = {
    "andean music": {"andes", "bolivia", "chile", "ecuador", "peru"},
    "blues": {"united states", "african diaspora", "africa"},
    "boogie-woogie": {"united states", "african diaspora"},
    "calypso music": {"trinidad and tobago", "caribbean"},
    "country music": {"united states"},
    "dancehall": {"jamaica"},
    "dikir barat": {"malaysia"},
    "disco": {"new york city", "united states"},
    "free jazz": {"new york city", "united states"},
    "gamelan": {"indonesia"},
    "gospel music": {"united states", "african diaspora"},
    "grunge": {"seattle", "washington (state)", "united states"},
    "hip-hop": {"new york city", "united states", "african diaspora"},
    "inuit music": {"nunavut", "canada"},
    "jazz": {"new orleans", "louisiana", "united states", "african diaspora"},
    "ma'luf": {"algeria", "libya", "tunisia"},
    "mazurka": {"poland"},
    "pacific reggae": {"polynesia", "melanesia", "oceania"},
    "pashto music": {"afghanistan", "pakistan"},
    "persian traditional music": {"iran"},
    "pinoy rock": {"philippines"},
    "pungmul": {"korea", "south korea"},
    "ragtime": {"united states", "african diaspora"},
    "reggae": {"jamaica", "caribbean"},
    "regional mexican": {"mexico"},
    "rhythm and blues": {"united states", "african diaspora"},
    "rock and roll": {"united states", "african diaspora"},
    "sawt (music)": {"bahrain", "kuwait"},
    "soca music": {"trinidad and tobago", "caribbean"},
}

BROAD_ROOT_CONTEXT_DENYLIST = {
    "africa": {
        "bomba (puerto rico)",
        "calypso music",
        "conga (music)",
        "cuban rumba",
        "cumbia",
        "kaiso",
        "salsa music",
        "samba",
        "soca music",
        "son cubano",
        "zouk",
    },
}

DEMONYM_OVERRIDES = {
    "afghanistan": {"afghan"},
    "africa": {"african"},
    "albania": {"albanian"},
    "argentina": {"argentine", "argentinian"},
    "armenia": {"armenian"},
    "australia": {"australian"},
    "austria": {"austrian"},
    "belarus": {"belarusian"},
    "belgium": {"belgian"},
    "brazil": {"brazilian"},
    "britain": {"british"},
    "bulgaria": {"bulgarian"},
    "canada": {"canadian"},
    "caribbean": {"caribbean"},
    "chile": {"chilean"},
    "china": {"chinese"},
    "colombia": {"colombian"},
    "croatia": {"croatian"},
    "cuba": {"cuban"},
    "dominican republic": {"dominican"},
    "denmark": {"danish"},
    "england": {"english"},
    "estonia": {"estonian"},
    "europe": {"european"},
    "finland": {"finnish"},
    "france": {"french"},
    "germany": {"german"},
    "ghana": {"ghanaian"},
    "greece": {"greek"},
    "haiti": {"haitian"},
    "hungary": {"hungarian"},
    "iceland": {"icelandic"},
    "india": {"indian"},
    "indonesia": {"indonesian"},
    "iran": {"iranian", "persian"},
    "ireland": {"irish"},
    "israel": {"israeli"},
    "italy": {"italian"},
    "jamaica": {"jamaican"},
    "japan": {"japanese"},
    "korea": {"korean"},
    "latvia": {"latvian"},
    "lithuania": {"lithuanian"},
    "mexico": {"mexican"},
    "mongolia": {"mongolian"},
    "morocco": {"moroccan"},
    "netherlands": {"dutch"},
    "norway": {"norwegian"},
    "pakistan": {"pakistani"},
    "peru": {"peruvian"},
    "puerto rico": {"puerto rican"},
    "philippines": {"philippine", "filipino"},
    "poland": {"polish"},
    "portugal": {"portuguese"},
    "romania": {"romanian"},
    "russia": {"russian"},
    "scotland": {"scottish"},
    "serbia": {"serbian"},
    "spain": {"spanish"},
    "sweden": {"swedish"},
    "thailand": {"thai"},
    "trinidad and tobago": {"trinidadian", "tobagonian"},
    "turkey": {"turkish"},
    "ukraine": {"ukrainian"},
    "united kingdom": {"british"},
    "united states": {"american", "u.s.", "us"},
    "venezuela": {"venezuelan"},
    "vietnam": {"vietnamese"},
    "wales": {"welsh"},
}


@dataclass(frozen=True)
class OwnershipDecision:
    ownership_class: str
    relation: str | None
    reason: str


@dataclass
class RegionOwnershipClassificationStats:
    rows_seen: int = 0
    rows_updated: int = 0
    owned_regional_genre: int = 0
    regional_style_mention: int = 0
    influence_or_context: int = 0
    bad_match: int = 0
    sample: list[str] = field(default_factory=list)


def _normalize(value: str | None) -> str:
    return " ".join((value or "").replace("_", " ").casefold().split())


def _key(value: str | None) -> str:
    return "_".join((value or "").casefold().split())


def _strip_music_region_title(title: str | None) -> str:
    lower = _normalize(title)
    for prefix in (
        "music of the ",
        "music of ",
        "music in the ",
        "music in ",
        "traditional music of ",
    ):
        if lower.startswith(prefix):
            return lower.removeprefix(prefix)
    return lower


def _tokens(value: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize(value)))


def region_name_variants(region_name: str | None, region_page_title: str | None = None) -> set[str]:
    variants = {_normalize(region_name), _strip_music_region_title(region_page_title)}
    variants = {item for item in variants if item}
    for variant in list(variants):
        variants.update(DEMONYM_OVERRIDES.get(variant, set()))
        if variant.endswith("a") and len(variant) > 4:
            variants.add(variant[:-1] + "an")
        if variant.endswith("y") and len(variant) > 4:
            variants.add(variant[:-1] + "ian")
    return {item for item in variants if item}


def title_is_region_specific(
    *,
    genre_title: str,
    region_name: str | None,
    region_page_title: str | None = None,
) -> bool:
    genre = _normalize(genre_title)
    if not genre:
        return False
    variants = region_name_variants(region_name, region_page_title)
    genre_tokens = _tokens(genre)
    for variant in variants:
        if not variant:
            continue
        variant_tokens = _tokens(variant)
        if len(variant) >= 4 and variant in genre:
            return True
        if variant_tokens and variant_tokens.issubset(genre_tokens):
            return True
        if len(variant) >= 3 and (f" in {variant}" in genre or f" of {variant}" in genre):
            return True
    return False


def _source_section_is_regional_list(section: str | None) -> bool:
    lower = _normalize(section)
    return any(
        term in lower
        for term in (
            "by country",
            "by region",
            "by territory",
            "regional styles",
            "regions",
            "traditions by country",
        )
    )


def _summary_has_origin_signal(genre_summary: str | None, region_name: str | None, region_page_title: str | None) -> bool:
    summary = _normalize(genre_summary)
    if not summary:
        return False
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    variants = _summary_origin_variants(region_name, region_page_title)
    origin_terms = ("originated", "emerged", "evolved", "developed")
    for sentence in sentences[:4]:
        if not any(term in sentence for term in origin_terms):
            continue
        for variant in variants:
            if not _contains_variant(sentence, variant):
                continue
            if _has_model_or_influence_only_context(sentence, variant):
                continue
            return True
    return False


def _summary_origin_variants(region_name: str | None, region_page_title: str | None) -> set[str]:
    variants = region_name_variants(region_name, region_page_title)
    normalized_region = _strip_music_region_title(region_page_title) or _normalize(region_name)
    if normalized_region == "united states":
        return {"united states", "u.s.", "us"}
    if normalized_region == "africa":
        return {"africa"}
    return {variant for variant in variants if len(variant) >= 4 or variant in {"uk", "us"}}


def _contains_variant(text: str, variant: str) -> bool:
    if variant in {"u.s.", "uk"}:
        return variant in text
    return re.search(rf"\b{re.escape(variant)}\b", text) is not None


def _has_model_or_influence_only_context(sentence: str, variant: str) -> bool:
    return any(
        re.search(pattern, sentence)
        for pattern in (
            rf"\bdeveloped\s+after\s+(?:the\s+)?{re.escape(variant)}\s+model\b",
            rf"\bborrow(?:ed|ing)\s+from\s+(?:the\s+)?{re.escape(variant)}\b",
            rf"\binfluenced\s+by\s+(?:the\s+)?{re.escape(variant)}\b",
            rf"\b{re.escape(variant)}-american\b",
        )
    )


def _origin_allowlist_matches(genre_title: str, region_name: str | None, region_page_title: str | None) -> bool:
    allowed_regions = ORIGIN_REGION_ALLOWLIST.get(_normalize(genre_title), set())
    if not allowed_regions:
        return False
    variants = region_name_variants(region_name, region_page_title)
    return bool(allowed_regions & variants)


def _is_broad_root_context_match(genre_title: str, region_name: str | None, region_page_title: str | None) -> bool:
    genre = _normalize(genre_title)
    variants = region_name_variants(region_name, region_page_title)
    return any(genre in BROAD_ROOT_CONTEXT_DENYLIST.get(variant, set()) for variant in variants)


def classify_region_genre_ownership(row: dict[str, Any]) -> OwnershipDecision:
    """Return graph semantics for one region-to-genre evidence row."""
    source_type = _key(row.get("source_type"))
    current_relation = _key(row.get("relation"))
    genre_title = str(row.get("genre_title") or row.get("title") or "")
    region_name = str(row.get("region_name") or "")
    region_page_title = row.get("region_page_title") or row.get("region_wikipedia_title")
    source_section = row.get("source_section")
    evidence_kind = _normalize(row.get("evidence_kind"))
    evidence_text = _normalize(row.get("evidence_text"))
    genre_summary = row.get("genre_summary")
    genre_lower = _normalize(genre_title)
    source_title_lower = _normalize(row.get("source_title"))

    if source_type in {"wikipedia_category", "wikipedia_list", "manual", "gpt_review"}:
        return OwnershipDecision(
            "owned_regional_genre",
            row.get("relation") or "regional_scene",
            "Category/list/manual evidence is treated as ownership evidence.",
        )

    if source_type != "wikipedia_article":
        return OwnershipDecision(
            "owned_regional_genre",
            row.get("relation") or "regional_scene",
            "Non-article source keeps its existing ownership semantics.",
        )

    if "excluded" in evidence_text or "not included" in evidence_text:
        return OwnershipDecision(
            "influence_or_context",
            INFLUENCE_RELATION,
            "Article evidence explicitly excludes or scopes away this target.",
        )

    if source_title_lower.startswith("list of "):
        return OwnershipDecision(
            "regional_style_mention",
            STYLE_MENTION_RELATION,
            "List article links are handled by list extraction, not regional page ownership.",
        )

    if title_is_region_specific(
        genre_title=genre_title,
        region_name=region_name,
        region_page_title=region_page_title,
    ):
        return OwnershipDecision(
            "owned_regional_genre",
            row.get("relation") if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
            "Target title is region-specific.",
        )

    if genre_lower.startswith(("music of ", "music in ", "traditional music of ")):
        if _source_section_is_regional_list(source_section) and evidence_kind in {
            "list_row_link",
            "table_row_link",
            "definition_row_link",
            "genre_section_link",
        }:
            return OwnershipDecision(
                "owned_regional_genre",
                row.get("relation") if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
                "Regional music page appeared in an explicit regional list section.",
            )
        return OwnershipDecision(
            "regional_style_mention",
            STYLE_MENTION_RELATION,
            "Linked regional music page is contextual, not direct child genre ownership.",
        )

    if _origin_allowlist_matches(genre_title, region_name, region_page_title):
        return OwnershipDecision(
            "owned_regional_genre",
            row.get("relation") if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
            "Target genre has an explicit curated origin-region match.",
        )

    if _is_broad_root_context_match(genre_title, region_name, region_page_title):
        return OwnershipDecision(
            "regional_style_mention",
            STYLE_MENTION_RELATION,
            "Broad root-region context is not direct regional genre ownership.",
        )

    if genre_lower in BROAD_STYLE_TITLES:
        return OwnershipDecision(
            "regional_style_mention",
            STYLE_MENTION_RELATION,
            "Regional music article discusses a local treatment of a broader style.",
        )

    if _summary_has_origin_signal(genre_summary, region_name, region_page_title):
        return OwnershipDecision(
            "owned_regional_genre",
            row.get("relation") if current_relation in OWNERSHIP_RELATIONS else "regional_scene",
            "Target genre summary has an origin signal for this region.",
        )

    if evidence_kind in {
        "section_heading",
        "lead_context_link",
        "genre_section_link",
        "list_row_link",
    }:
        return OwnershipDecision(
            "regional_style_mention",
            STYLE_MENTION_RELATION,
            "Regional music article discusses a local treatment of a broader style.",
        )

    return OwnershipDecision(
        "regional_style_mention",
        STYLE_MENTION_RELATION,
        "Article link lacks region-specific or origin evidence for graph ownership.",
    )


async def classify_existing_region_genre_ownership(*, sample_size: int = 25) -> RegionOwnershipClassificationStats:
    """Classify existing article-derived accepted/proposed region-genre rows."""
    await apply_migrations()
    stats = RegionOwnershipClassificationStats()
    engine = get_engine()

    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            rel.id,
                            rel.region_id,
                            rel.genre_id,
                            rel.relation,
                            rel.source_type,
                            rel.source_url,
                            rel.source_title,
                            rel.source_section,
                            rel.evidence_text,
                            rel.raw_payload ->> 'evidence_kind' AS evidence_kind,
                            region.canonical_name AS region_name,
                            region.wikipedia_title AS region_wikipedia_title,
                            genre.wikipedia_title AS genre_title,
                            genre.summary AS genre_summary
                        FROM wg_region_genre_relationships rel
                        JOIN wg_regions region ON region.id = rel.region_id
                        JOIN wg_genres genre ON genre.id = rel.genre_id
                        WHERE rel.status IN ('accepted', 'proposed', 'needs_review')
                          AND rel.source_type = 'wikipedia_article'
                          AND rel.raw_payload ->> 'extractor_model' LIKE 'deterministic-region-page-links-v%'
                        ORDER BY rel.id
                    """)
                )
            )
            .mappings()
            .fetchall()
        )

        stats.rows_seen = len(rows)
        for row in rows:
            row_dict = dict(row)
            decision = classify_region_genre_ownership(row_dict)
            if decision.ownership_class == "owned_regional_genre":
                stats.owned_regional_genre += 1
            elif decision.ownership_class == "regional_style_mention":
                stats.regional_style_mention += 1
            elif decision.ownership_class == "influence_or_context":
                stats.influence_or_context += 1
            elif decision.ownership_class == "bad_match":
                stats.bad_match += 1

            target_relation = decision.relation or row_dict["relation"]
            duplicate_id = None
            if target_relation != row_dict["relation"]:
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
                        "relation": target_relation,
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
                            review_reason = :review_reason,
                            reviewer_model = :reviewer_model,
                            raw_payload = target.raw_payload
                                || source.raw_payload
                                || jsonb_build_object(
                                    'ownership_review',
                                    jsonb_build_object(
                                        'ownership_class', CAST(:ownership_class AS text),
                                        'relation', CAST(:relation AS text),
                                        'reason', CAST(:review_reason AS text),
                                        'reviewer_model', CAST(:reviewer_model AS text)
                                    )
                                ),
                            updated_at = now()
                        FROM wg_region_genre_relationships source
                        WHERE target.id = :duplicate_id
                          AND source.id = :id
                    """),
                    {
                        "id": row_dict["id"],
                        "duplicate_id": duplicate_id,
                        "relation": target_relation,
                        "ownership_class": decision.ownership_class,
                        "review_reason": decision.reason,
                        "reviewer_model": REVIEW_MODEL,
                    },
                )
                result = await conn.execute(
                    text("DELETE FROM wg_region_genre_relationships WHERE id = :id"),
                    {"id": row_dict["id"]},
                )
                stats.rows_updated += result.rowcount or 0
                if len(stats.sample) < sample_size:
                    stats.sample.append(
                        f"{decision.ownership_class}: {row_dict['region_name']} -> "
                        f"{row_dict['genre_title']} ({decision.reason})"
                    )
                continue

            result = await conn.execute(
                text("""
                    UPDATE wg_region_genre_relationships
                    SET relation = :relation,
                        review_reason = :review_reason,
                        reviewer_model = :reviewer_model,
                        raw_payload = raw_payload || jsonb_build_object(
                            'ownership_review',
                            jsonb_build_object(
                                'ownership_class', CAST(:ownership_class AS text),
                                'relation', CAST(:relation AS text),
                                'reason', CAST(:review_reason AS text),
                                'reviewer_model', CAST(:reviewer_model AS text)
                            )
                        ),
                        updated_at = now()
                    WHERE id = :id
                """),
                {
                    "id": row_dict["id"],
                    "relation": target_relation,
                    "ownership_class": decision.ownership_class,
                    "review_reason": decision.reason,
                    "reviewer_model": REVIEW_MODEL,
                },
            )
            stats.rows_updated += result.rowcount or 0
            if len(stats.sample) < sample_size:
                stats.sample.append(
                    f"{decision.ownership_class}: {row_dict['region_name']} -> "
                    f"{row_dict['genre_title']} ({decision.reason})"
                )

    logger.info(
        "region_ownership_classification_complete",
        rows_seen=stats.rows_seen,
        rows_updated=stats.rows_updated,
        owned_regional_genre=stats.owned_regional_genre,
        regional_style_mention=stats.regional_style_mention,
        influence_or_context=stats.influence_or_context,
        bad_match=stats.bad_match,
    )
    return stats
