"""Region graph seed routines.

The region graph is the staging layer for comprehensive regional coverage.
This module only seeds the current approved ``Music of ...`` pages; later
workers can add hierarchy, category evidence, and list-page genre population.
"""

from __future__ import annotations

import re
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

APPROVED_MUSIC_PAGE_SOURCE = "approved_music_page"
PRIMARY_MUSIC_PAGE_ROLE = "primary_music_page"

REGION_NAME_ALIASES = {
    "african": "Africa",
    "american": "United States",
    "asian": "Asia",
    "australasia & oceania": "Oceania",
    "australian": "Australia",
    "british": "United Kingdom",
    "chinese": "China",
    "danish": "Denmark",
    "dutch": "Netherlands",
    "european": "Europe",
    "french": "France",
    "german": "Germany",
    "italian": "Italy",
    "japanese": "Japan",
    "latin & south american": "Latin America",
    "latin american": "Latin America",
    "middle eastern": "Middle East",
    "north american": "North America",
    "oceania and australia": "Oceania",
    "south american": "South America",
}

REGIONAL_SECTIONS_FOR_GENERAL_GENRE_LIST = {
    "african",
    "asian",
    "australasia & oceania",
    "european",
    "latin & south american",
    "middle eastern",
    "north american",
}

REGIONAL_STYLE_PARENT_ALIASES = {
    "albanian": "Albania",
    "algerian": "Algeria",
    "argentine": "Argentina",
    "armenian": "Armenia",
    "assyrian/syriac": "Middle East",
    "austrian": "Austria",
    "azerbaijani": "Azerbaijan",
    "bahamian": "Bahamas",
    "bangladeshi": "Bangladesh",
    "bhutanese": "Bhutan",
    "bosnian": "Bosnia and Herzegovina",
    "brazilian": "Brazil",
    "bulgarian": "Bulgaria",
    "canadian": "Canada",
    "celtic": "Europe",
    "central american": "Central America",
    "chilean": "Chile",
    "colombian": "Colombia",
    "colonial mexico": "Mexico",
    "costa rican": "Costa Rica",
    "cuban": "Cuba",
    "czech": "Czech Republic",
    "côte d'ivoire": "Africa",
    "dominican": "Dominican Republic",
    "dutch west indies": "Caribbean",
    "elizabethan era": "England",
    "estonian": "Estonia",
    "egyptian": "Egypt",
    "finnish": "Finland",
    "franco-flemish": "Europe",
    "gaelic": "Celtic",
    "georgian": "Georgia",
    "ghanaian": "Ghana",
    "greek": "Greece",
    "haitian": "Haiti",
    "hawaiian": "Hawaii",
    "indian": "India",
    "indonesian": "Indonesia",
    "iranian": "Iran",
    "israeli": "Israel",
    "jamaican": "Jamaica",
    "kenyan": "Kenya",
    "korean": "Korea",
    "liberian": "Liberia",
    "lithuanian": "Lithuania",
    "macedonian": "Republic of Macedonia",
    "malaysian": "Malaysia",
    "maltese": "Malta",
    "mauritian": "Mauritius",
    "medieval islamic world": "Middle East",
    "mexican": "Mexico",
    "moldovan": "Moldova",
    "moravian": "Czech Republic",
    "moroccan": "Morocco",
    "nepali": "Nepal",
    "nepalese": "Nepal",
    "nigerian": "Nigeria",
    "north korean": "North Korea",
    "norwegian": "Norway",
    "panamanian": "Panama",
    "palestinian": "Palestine",
    "pakistani": "Pakistan",
    "paraguayan": "Paraguay",
    "peruvian": "Peru",
    "philippine": "Philippines",
    "puerto rican": "Puerto Rico",
    "republic of macedonia": "Europe",
    "serbian": "Serbia",
    "scottish": "Scotland",
    "senegalese": "Senegal",
    "sierra leonean": "Sierra Leone",
    "slovak": "Slovakia",
    "slovenian": "Slovenia",
    "south african": "South Africa",
    "spanish": "Spain",
    "sri lankan": "Sri Lanka",
    "sub-saharan african": "Africa",
    "sudanese": "Sudan",
    "swaziland": "Africa",
    "swiss": "Switzerland",
    "swedish": "Sweden",
    "tajik": "Tajikistan",
    "thai": "Thailand",
    "tunis": "Tunisia",
    "turkish": "Turkey",
    "uruguayan": "Uruguay",
    "vatican city": "Europe",
    "venezuelan": "Venezuela",
    "vietnamese": "Vietnam",
    "yemeni": "Yemen",
    "yucatán, mexico": "Mexico",
    "ancient persia": "Iran",
    "immigrant communities in the united states": "United States",
}


@dataclass(frozen=True)
class MusicRegionPage:
    genre_id: str
    wikipedia_title: str
    wikipedia_url: str | None
    region_id: str
    region_name: str


@dataclass
class RegionGraphSeedStats:
    music_pages_found: int = 0
    regions_upserted: int = 0
    sources_upserted: int = 0
    music_pages_upserted: int = 0
    skipped_titles: list[str] = field(default_factory=list)
    dry_run: bool = False
    sample: list[MusicRegionPage] = field(default_factory=list)


@dataclass
class RegionRelationshipProposalStats:
    candidates_seen: int = 0
    regions_upserted: int = 0
    sources_upserted: int = 0
    region_relationships_upserted: int = 0
    region_genre_relationships_upserted: int = 0
    music_pages_upserted: int = 0
    skipped_candidates: int = 0
    sample: list[str] = field(default_factory=list)


def region_name_from_music_title(title: str) -> str | None:
    """Return the region portion of a ``Music of ...`` title."""
    match = re.match(r"^music of (?:the )?(.+)$", title.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    name = re.sub(r"\s*\(country\)\s*$", "", match.group(1), flags=re.IGNORECASE).strip()
    return " ".join(name.split()) or None


def region_name_from_music_in_title(title: str) -> str | None:
    match = re.match(r"^music in (?:the )?(.+)$", title.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return " ".join(match.group(1).split()) or None


def title_without_category(title: str) -> str:
    return re.sub(r"^category:", "", title.strip(), flags=re.IGNORECASE).strip()


def clean_region_name(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(
        r"^dependent territories of (?:the )?(.+)$",
        r"\1",
        name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+by\s+.+$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*\(country\)\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(?:the)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = REGION_NAME_ALIASES.get(cleaned.lower(), cleaned)
    return " ".join(cleaned.split()) or None


def region_name_from_title(title: str | None) -> str | None:
    if not title:
        return None
    clean = title_without_category(title)
    return clean_region_name(
        region_name_from_music_title(clean) or region_name_from_music_in_title(clean)
    )


def candidate_region_name_for_row(row: dict[str, Any]) -> str | None:
    return clean_region_name(
        row.get("suggested_region_name")
        or region_name_from_title(row.get("title"))
        or source_region_name(row.get("title"))
    )


def source_region_name(source_title: str | None, source_section: str | None = None) -> str | None:
    generic_sections = {
        "",
        "by continent or other international region",
        "by ethnicity or origin",
        "by religion",
        "external links",
        "immigrant communities",
        "international ethnic groups",
        "native american ethnic groups",
        "native sub-saharan african ethnic groups",
        "other",
        "pop",
        "references",
        "see also",
        "traditional folk",
    }
    section_lower = source_section.strip().lower() if source_section else ""
    source_clean = title_without_category(source_title) if source_title else None
    if section_lower.startswith("by "):
        section_lower = ""
    if source_clean == "List of music genres and styles":
        if section_lower not in REGIONAL_SECTIONS_FOR_GENERAL_GENRE_LIST:
            section_lower = ""
            source_section = None
    if source_section and section_lower and section_lower not in generic_sections:
        return clean_region_name(source_section)
    if not source_title:
        return None
    clean = source_clean or title_without_category(source_title)
    explicit = region_name_from_title(clean)
    if explicit:
        return explicit
    match = re.match(r"^list of (.+?) music genres", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    match = re.match(r"^list of (.+?) folk music traditions", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    match = re.match(r"^list of musical genres of (?:the )?(.+)$", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    match = re.match(r"^(.+?) styles of music$", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    match = re.match(r"^(.+?) music genres$", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    match = re.match(r"^(.+?) (folk|traditional|indigenous|popular) music$", clean, flags=re.IGNORECASE)
    if match:
        return clean_region_name(match.group(1))
    return None


def parent_region_name_for_candidate(row: dict[str, Any]) -> str | None:
    raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
    if row.get("source_type") == "wikipedia_list" and "list_context_region" in raw_payload:
        context_region = clean_region_name(raw_payload.get("list_context_region"))
        return context_region
    parent_name = source_region_name(
        row.get("source_title"),
        row.get("source_section"),
    )
    if parent_name:
        parent_name = REGIONAL_STYLE_PARENT_ALIASES.get(parent_name.lower(), parent_name)
    candidate_name = candidate_region_name_for_row(row)
    if parent_name and candidate_name and parent_name.lower() == candidate_name.lower():
        return REGIONAL_STYLE_PARENT_ALIASES.get(parent_name.lower(), parent_name)
    if candidate_name:
        return REGIONAL_STYLE_PARENT_ALIASES.get(candidate_name.lower(), parent_name)
    return parent_name


def normalize_genre_title(title: str) -> str:
    clean = title_without_category(title).replace("_", " ").strip()
    return " ".join(clean.split())


def infer_region_kind(name: str | None, source_title: str | None = None) -> str:
    lower = " ".join(part.lower() for part in (name or "", source_title or "") if part)
    if any(term in lower for term in ("african diaspora", "diaspora")):
        return "diaspora_region"
    if any(term in lower for term in ("ancient", "medieval", "renaissance", "history of")):
        return "historical_region"
    if " by city" in lower or lower.startswith("music in "):
        return "city"
    if "dependent territory" in lower or "territor" in lower:
        return "territory"
    if any(term in lower for term in ("continent", "africa", "asia", "europe", "oceania")):
        return "continent" if lower.strip() in {"africa", "asia", "europe", "oceania"} else "subregion"
    if any(
        term in lower
        for term in (
            "caribbean",
            "latin america",
            "middle eastern",
            "north america",
            "south america",
            "central america",
            "nordic",
            "celtic",
        )
    ):
        return "cultural_region"
    return "unknown"


def relation_for_region_edge(candidate_type: str, source_title: str | None) -> str:
    lower = " ".join(part.lower() for part in (candidate_type, source_title or "") if part)
    if "diaspora" in lower:
        return "diaspora_region_of"
    if any(term in lower for term in ("ancient", "medieval", "renaissance", "history")):
        return "historical_region_of"
    if " by " in lower or "dependent territor" in lower or "category:music in " in lower:
        return "admin_parent"
    if any(term in lower for term in ("cultural", "celtic", "caribbean", "middle eastern")):
        return "cultural_region_of"
    if re.search(r"\blatin(?:\s+america|\s+american)?\b", lower):
        return "cultural_region_of"
    return "part_of"


def relation_for_region_genre(row: dict[str, Any], region_kind: str) -> str:
    lower = " ".join(
        str(row.get(key) or "").lower()
        for key in ("candidate_type", "title", "source_title", "source_section")
    )
    if "diaspora" in lower:
        return "diaspora_region"
    if "indigenous" in lower:
        return "indigenous_region"
    if "traditional" in lower or "folk" in lower:
        return "traditional_region"
    if any(term in lower for term in ("ancient", "medieval", "renaissance", "history")):
        return "historical_region"
    if region_kind == "city":
        return "local_scene"
    if "cultural_region_page" in lower:
        return "cultural_region"
    return "regional_scene"


def is_region_node_candidate(candidate_type: str) -> bool:
    return candidate_type in {
        "music_region_page",
        "music_region_category",
        "region_container_category",
    }


def normalize_region_id(name: str) -> str:
    """Create the stable region id used by ``wg_regions``."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return f"region-{slug or 'unknown'}"


def build_music_region_page(row: dict[str, object]) -> MusicRegionPage | None:
    title = str(row["wikipedia_title"])
    region_name = region_name_from_music_title(title)
    if not region_name:
        return None
    return MusicRegionPage(
        genre_id=str(row["id"]),
        wikipedia_title=title,
        wikipedia_url=str(row["wikipedia_url"]) if row.get("wikipedia_url") else None,
        region_id=normalize_region_id(region_name),
        region_name=region_name,
    )


async def seed_music_region_pages(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
) -> RegionGraphSeedStats:
    """Seed region graph rows from approved ``Music of ...`` genre pages."""
    await apply_migrations()
    stats = RegionGraphSeedStats(dry_run=dry_run)
    engine = get_engine()

    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                SELECT id, wikipedia_title, wikipedia_url
                FROM wg_genres
                WHERE deleted_at IS NULL
                  AND is_non_genre = false
                  AND wikipedia_title ILIKE 'Music of %'
                ORDER BY wikipedia_title
            """)
                )
            )
            .mappings()
            .fetchall()
        )

        pages: list[MusicRegionPage] = []
        for row in rows:
            page = build_music_region_page(dict(row))
            if page:
                pages.append(page)
            else:
                stats.skipped_titles.append(row["wikipedia_title"])

        stats.music_pages_found = len(pages)
        stats.sample = pages[:sample_size]
        if dry_run or not pages:
            return stats

        await conn.execute(
            text("""
                INSERT INTO wg_regions (
                    id,
                    canonical_name,
                    kind,
                    wikipedia_title,
                    confidence,
                    raw_payload,
                    updated_at
                )
                VALUES (
                    :region_id,
                    :region_name,
                    'unknown',
                    :wikipedia_title,
                    0.8,
                    jsonb_build_object('seed', 'music_of_page'),
                    now()
                )
                ON CONFLICT (id) DO UPDATE
                SET canonical_name = excluded.canonical_name,
                    kind = CASE
                        WHEN wg_regions.kind = 'unknown' THEN excluded.kind
                        ELSE wg_regions.kind
                    END,
                    wikipedia_title = excluded.wikipedia_title,
                    confidence = greatest(wg_regions.confidence, excluded.confidence),
                    updated_at = now()
            """),
            [
                {
                    "region_id": page.region_id,
                    "region_name": page.region_name,
                    "wikipedia_title": page.wikipedia_title,
                }
                for page in pages
            ],
        )
        stats.regions_upserted = len(pages)

        await conn.execute(
            text("""
                INSERT INTO wg_region_sources (
                    region_id,
                    source_type,
                    source_url,
                    source_title,
                    evidence_text,
                    confidence,
                    raw_payload
                )
                VALUES (
                    :region_id,
                    :source_type,
                    :source_url,
                    :source_title,
                    :evidence_text,
                    0.8,
                    jsonb_build_object('genre_id', CAST(:genre_id AS text))
                )
                ON CONFLICT (
                    coalesce(region_id, ''),
                    source_type,
                    coalesce(source_url, ''),
                    coalesce(source_title, ''),
                    coalesce(source_section, '')
                )
                DO UPDATE
                SET evidence_text = excluded.evidence_text,
                    confidence = greatest(wg_region_sources.confidence, excluded.confidence),
                    raw_payload = excluded.raw_payload
            """),
            [
                {
                    "region_id": page.region_id,
                    "source_type": APPROVED_MUSIC_PAGE_SOURCE,
                    "source_url": page.wikipedia_url,
                    "source_title": page.wikipedia_title,
                    "evidence_text": f"Approved genre row for {page.wikipedia_title}.",
                    "genre_id": page.genre_id,
                }
                for page in pages
            ],
        )
        stats.sources_upserted = len(pages)

        source_rows = (
            (
                await conn.execute(
                    text("""
                SELECT region_id, source_title, id
                FROM wg_region_sources
                WHERE source_type = :source_type
                  AND source_title = ANY(:titles)
            """),
                    {
                        "source_type": APPROVED_MUSIC_PAGE_SOURCE,
                        "titles": [page.wikipedia_title for page in pages],
                    },
                )
            )
            .mappings()
            .fetchall()
        )
        source_id_by_key = {
            (row["region_id"], row["source_title"]): row["id"] for row in source_rows
        }

        await conn.execute(
            text("""
                INSERT INTO wg_region_music_pages (
                    region_id,
                    genre_id,
                    role,
                    source_id,
                    source_type,
                    source_url,
                    source_title,
                    evidence_text,
                    confidence,
                    raw_payload
                )
                VALUES (
                    :region_id,
                    :genre_id,
                    :role,
                    :source_id,
                    :source_type,
                    :source_url,
                    :source_title,
                    :evidence_text,
                    0.8,
                    jsonb_build_object('region_name', CAST(:region_name AS text))
                )
                ON CONFLICT (region_id, genre_id, role, source_type) DO UPDATE
                SET source_id = excluded.source_id,
                    source_url = excluded.source_url,
                    source_title = excluded.source_title,
                    evidence_text = excluded.evidence_text,
                    confidence = greatest(
                        wg_region_music_pages.confidence,
                        excluded.confidence
                    ),
                    raw_payload = excluded.raw_payload
            """),
            [
                {
                    "region_id": page.region_id,
                    "genre_id": page.genre_id,
                    "role": PRIMARY_MUSIC_PAGE_ROLE,
                    "source_id": source_id_by_key.get((page.region_id, page.wikipedia_title)),
                    "source_type": APPROVED_MUSIC_PAGE_SOURCE,
                    "source_url": page.wikipedia_url,
                    "source_title": page.wikipedia_title,
                    "evidence_text": f"{page.wikipedia_title} is the primary music page for {page.region_name}.",
                    "region_name": page.region_name,
                }
                for page in pages
            ],
        )
        stats.music_pages_upserted = len(pages)

    logger.info(
        "region_graph_seed_complete",
        music_pages_found=stats.music_pages_found,
        regions_upserted=stats.regions_upserted,
        sources_upserted=stats.sources_upserted,
        music_pages_upserted=stats.music_pages_upserted,
    )
    return stats


async def build_region_relationship_proposals(
    *,
    reset: bool = False,
    sample_size: int = 25,
) -> RegionRelationshipProposalStats:
    """Build Phase 3 staging relationships from accepted regional candidates."""
    await apply_migrations()
    stats = RegionRelationshipProposalStats()
    engine = get_engine()

    async with engine.begin() as conn:
        if reset:
            await conn.execute(text("DELETE FROM wg_region_genre_relationships"))
            await conn.execute(text("DELETE FROM wg_region_relationships"))
            await conn.execute(
                text("DELETE FROM wg_region_music_pages WHERE role <> 'primary_music_page'")
            )
            await conn.execute(
                text("DELETE FROM wg_region_sources WHERE raw_payload ->> 'phase' = 'phase3'")
            )
            await conn.execute(
                text("""
                    DELETE FROM wg_regions r
                    WHERE r.raw_payload ->> 'phase' = 'phase3'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM wg_region_music_pages p
                          WHERE p.region_id = r.id
                      )
                """)
            )

        genre_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT id, wikipedia_title
                        FROM wg_genres
                        WHERE deleted_at IS NULL
                          AND is_non_genre = false
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        genre_by_title = {
            normalize_genre_title(row["wikipedia_title"]).lower(): row["id"]
            for row in genre_rows
        }

        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            candidate_key,
                            candidate_type,
                            title,
                            normalized_title,
                            suggested_region_id,
                            suggested_region_name,
                            source_key,
                            source_type,
                            source_title,
                            source_url,
                            source_section,
                            evidence_text,
                            confidence,
                            extractor_model,
                            raw_payload
                        FROM wg_region_candidates
                        WHERE status = 'accepted'
                        ORDER BY candidate_type, normalized_title, source_title
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.candidates_seen = len(rows)

        region_source_ids: dict[tuple[str, str, str | None, str | None, str | None], int] = {}

        async def upsert_region(
            name: str | None,
            *,
            wikipedia_title: str | None = None,
            source_title: str | None = None,
            confidence: float = 0.65,
        ) -> str | None:
            clean_name = clean_region_name(name)
            if not clean_name:
                return None
            region_id = normalize_region_id(clean_name)
            kind = infer_region_kind(clean_name, source_title)
            await conn.execute(
                text("""
                    INSERT INTO wg_regions (
                        id,
                        canonical_name,
                        kind,
                        wikipedia_title,
                        confidence,
                        raw_payload,
                        updated_at
                    )
                    VALUES (
                        :region_id,
                        :canonical_name,
                        :kind,
                        :wikipedia_title,
                        :confidence,
                        jsonb_build_object('phase', 'phase3'),
                        now()
                    )
                    ON CONFLICT (id) DO UPDATE
                    SET canonical_name = excluded.canonical_name,
                        kind = CASE
                            WHEN wg_regions.kind = 'unknown' THEN excluded.kind
                            ELSE wg_regions.kind
                        END,
                        wikipedia_title = COALESCE(wg_regions.wikipedia_title, excluded.wikipedia_title),
                        confidence = greatest(wg_regions.confidence, excluded.confidence),
                        raw_payload = wg_regions.raw_payload || excluded.raw_payload,
                        updated_at = now()
                """),
                {
                    "region_id": region_id,
                    "canonical_name": clean_name,
                    "kind": kind,
                    "wikipedia_title": wikipedia_title,
                    "confidence": confidence,
                },
            )
            stats.regions_upserted += 1
            return region_id

        async def upsert_source(row: dict[str, Any], region_id: str | None) -> int | None:
            if not region_id:
                return None
            source_key = (
                region_id,
                row["source_type"],
                row.get("source_url"),
                row.get("source_title"),
                row.get("source_section"),
            )
            if source_key in region_source_ids:
                return region_source_ids[source_key]
            await conn.execute(
                text("""
                    INSERT INTO wg_region_sources (
                        region_id,
                        source_type,
                        source_url,
                        source_title,
                        source_section,
                        evidence_text,
                        extractor_model,
                        confidence,
                        raw_payload
                    )
                    VALUES (
                        :region_id,
                        :source_type,
                        :source_url,
                        :source_title,
                        :source_section,
                        :evidence_text,
                        :extractor_model,
                        :confidence,
                        :raw_payload
                    )
                    ON CONFLICT (
                        coalesce(region_id, ''),
                        source_type,
                        coalesce(source_url, ''),
                        coalesce(source_title, ''),
                        coalesce(source_section, '')
                    )
                    DO UPDATE
                    SET evidence_text = excluded.evidence_text,
                        extractor_model = excluded.extractor_model,
                        confidence = greatest(wg_region_sources.confidence, excluded.confidence),
                        raw_payload = wg_region_sources.raw_payload || excluded.raw_payload
                """),
                {
                    "region_id": region_id,
                    "source_type": row["source_type"],
                    "source_url": row.get("source_url"),
                    "source_title": row.get("source_title"),
                    "source_section": row.get("source_section"),
                    "evidence_text": row.get("evidence_text"),
                    "extractor_model": row.get("extractor_model"),
                    "confidence": row["confidence"],
                    "raw_payload": json_payload(row),
                },
            )
            source_id = await conn.scalar(
                text("""
                    SELECT id
                    FROM wg_region_sources
                    WHERE region_id = :region_id
                      AND source_type = :source_type
                      AND coalesce(source_url, '') = coalesce(:source_url, '')
                      AND coalesce(source_title, '') = coalesce(:source_title, '')
                      AND coalesce(source_section, '') = coalesce(:source_section, '')
                """),
                {
                    "region_id": region_id,
                    "source_type": row["source_type"],
                    "source_url": row.get("source_url"),
                    "source_title": row.get("source_title"),
                    "source_section": row.get("source_section"),
                },
            )
            if source_id is not None:
                region_source_ids[source_key] = int(source_id)
                stats.sources_upserted += 1
            return int(source_id) if source_id is not None else None

        for raw_row in rows:
            row = dict(raw_row)
            candidate_region_name = candidate_region_name_for_row(row)
            parent_region_name = parent_region_name_for_candidate(row)
            title = normalize_genre_title(row["title"])
            genre_id = genre_by_title.get(title.lower())

            candidate_region_id = await upsert_region(
                candidate_region_name,
                wikipedia_title=title if candidate_region_name else None,
                source_title=row.get("source_title"),
                confidence=row["confidence"],
            )
            parent_region_id = await upsert_region(
                parent_region_name,
                source_title=row.get("source_title"),
                confidence=max(0.62, float(row["confidence"]) - 0.05),
            )

            source_region_id = candidate_region_id or parent_region_id
            source_id = await upsert_source(row, source_region_id)

            if (
                candidate_region_id
                and parent_region_id
                and candidate_region_id != parent_region_id
                and (
                    row["source_type"] == "wikipedia_category"
                    or (
                        row["source_type"] == "wikipedia_list"
                        and isinstance(row.get("raw_payload"), dict)
                        and row["raw_payload"].get("list_context_region")
                    )
                )
            ):
                relation = (
                    "part_of"
                    if row["source_type"] == "wikipedia_list"
                    else relation_for_region_edge(row["candidate_type"], row.get("source_title"))
                )
                await conn.execute(
                    text("""
                        INSERT INTO wg_region_relationships (
                            from_region_id,
                            to_region_id,
                            relation,
                            source_id,
                            source_type,
                            source_url,
                            source_title,
                            source_section,
                            evidence_text,
                            confidence,
                            raw_payload
                        )
                        VALUES (
                            :from_region_id,
                            :to_region_id,
                            :relation,
                            :source_id,
                            :source_type,
                            :source_url,
                            :source_title,
                            :source_section,
                            :evidence_text,
                            :confidence,
                            :raw_payload
                        )
                        ON CONFLICT (
                            from_region_id,
                            to_region_id,
                            relation,
                            source_type,
                            coalesce(source_url, ''),
                            coalesce(source_title, ''),
                            coalesce(source_section, '')
                        )
                        DO UPDATE
                        SET source_id = excluded.source_id,
                            evidence_text = excluded.evidence_text,
                            confidence = greatest(
                                wg_region_relationships.confidence,
                                excluded.confidence
                            ),
                            raw_payload = wg_region_relationships.raw_payload || excluded.raw_payload
                    """),
                    {
                        "from_region_id": candidate_region_id,
                        "to_region_id": parent_region_id,
                        "relation": relation,
                        "source_id": source_id,
                        "source_type": row["source_type"],
                        "source_url": row.get("source_url"),
                        "source_title": row.get("source_title"),
                        "source_section": row.get("source_section"),
                        "evidence_text": row.get("evidence_text"),
                        "confidence": row["confidence"],
                        "raw_payload": json_payload(row, phase_relation="region_region"),
                    },
                )
                stats.region_relationships_upserted += 1
                add_sample(
                    stats,
                    f"{candidate_region_name} --{relation}--> {parent_region_name}",
                    sample_size,
                )

            if genre_id and parent_region_id and not is_region_node_candidate(row["candidate_type"]):
                region_kind = infer_region_kind(parent_region_name, row.get("source_title"))
                relation = relation_for_region_genre(row, region_kind)
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
                            'proposed',
                            :raw_payload,
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
                        SET source_id = excluded.source_id,
                            evidence_text = excluded.evidence_text,
                            confidence = greatest(
                                wg_region_genre_relationships.confidence,
                                excluded.confidence
                            ),
                            raw_payload = wg_region_genre_relationships.raw_payload || excluded.raw_payload,
                            updated_at = now()
                    """),
                    {
                        "region_id": parent_region_id,
                        "genre_id": genre_id,
                        "relation": relation,
                        "source_id": source_id,
                        "source_type": row["source_type"],
                        "source_url": row.get("source_url"),
                        "source_title": row.get("source_title"),
                        "source_section": row.get("source_section"),
                        "evidence_text": row.get("evidence_text"),
                        "confidence": row["confidence"],
                        "raw_payload": json_payload(row, phase_relation="region_genre"),
                    },
                )
                stats.region_genre_relationships_upserted += 1
                add_sample(stats, f"{parent_region_name} --{relation}--> {title}", sample_size)

            if genre_id and candidate_region_id and row["candidate_type"] == "music_region_page":
                await conn.execute(
                    text("""
                        INSERT INTO wg_region_music_pages (
                            region_id,
                            genre_id,
                            role,
                            source_id,
                            source_type,
                            source_url,
                            source_title,
                            evidence_text,
                            confidence,
                            raw_payload
                        )
                        VALUES (
                            :region_id,
                            :genre_id,
                            'primary_music_page',
                            :source_id,
                            :source_type,
                            :source_url,
                            :source_title,
                            :evidence_text,
                            :confidence,
                            :raw_payload
                        )
                        ON CONFLICT (region_id, genre_id, role, source_type) DO UPDATE
                        SET source_id = excluded.source_id,
                            source_url = excluded.source_url,
                            source_title = excluded.source_title,
                            evidence_text = excluded.evidence_text,
                            confidence = greatest(
                                wg_region_music_pages.confidence,
                                excluded.confidence
                            ),
                            raw_payload = wg_region_music_pages.raw_payload || excluded.raw_payload
                    """),
                    {
                        "region_id": candidate_region_id,
                        "genre_id": genre_id,
                        "source_id": source_id,
                        "source_type": row["source_type"],
                        "source_url": row.get("source_url"),
                        "source_title": row.get("source_title"),
                        "evidence_text": row.get("evidence_text"),
                        "confidence": row["confidence"],
                        "raw_payload": json_payload(row, phase_relation="music_page"),
                    },
                )
                stats.music_pages_upserted += 1

            if not (candidate_region_id or parent_region_id or genre_id):
                stats.skipped_candidates += 1

        for child_name, parent_name in REGIONAL_STYLE_PARENT_ALIASES.items():
            child_region_name = clean_region_name(child_name)
            parent_region_name = clean_region_name(parent_name)
            child_region_id = await upsert_region(
                child_region_name,
                source_title="manual regional hierarchy aliases",
                confidence=0.82,
            )
            parent_region_id = await upsert_region(
                parent_region_name,
                source_title="manual regional hierarchy aliases",
                confidence=0.82,
            )
            if not child_region_id or not parent_region_id or child_region_id == parent_region_id:
                continue
            await conn.execute(
                text("""
                    INSERT INTO wg_region_relationships (
                        from_region_id,
                        to_region_id,
                        relation,
                        source_type,
                        source_title,
                        evidence_text,
                        confidence,
                        raw_payload
                    )
                    VALUES (
                        :from_region_id,
                        :to_region_id,
                        'part_of',
                        'manual',
                        'regional parent alias',
                        :evidence_text,
                        0.82,
                        jsonb_build_object(
                            'phase',
                            'phase3',
                            'phase_relation',
                            'region_region',
                            'relation_source',
                            'regional_parent_alias'
                        )
                    )
                    ON CONFLICT (
                        from_region_id,
                        to_region_id,
                        relation,
                        source_type,
                        coalesce(source_url, ''),
                        coalesce(source_title, ''),
                        coalesce(source_section, '')
                    )
                    DO UPDATE
                    SET evidence_text = excluded.evidence_text,
                        confidence = greatest(
                            wg_region_relationships.confidence,
                            excluded.confidence
                        ),
                        raw_payload = wg_region_relationships.raw_payload || excluded.raw_payload
                """),
                {
                    "from_region_id": child_region_id,
                    "to_region_id": parent_region_id,
                    "evidence_text": (
                        f"Deterministic regional-name alias maps {child_region_name} "
                        f"to {parent_region_name}."
                    ),
                },
            )
            stats.region_relationships_upserted += 1
            add_sample(stats, f"{child_region_name} --part_of--> {parent_region_name}", sample_size)

    logger.info(
        "region_relationship_proposals_complete",
        candidates_seen=stats.candidates_seen,
        regions_upserted=stats.regions_upserted,
        region_relationships_upserted=stats.region_relationships_upserted,
        region_genre_relationships_upserted=stats.region_genre_relationships_upserted,
    )
    return stats


def json_payload(row: dict[str, Any], *, phase_relation: str | None = None) -> str:
    payload: dict[str, Any] = {
        "phase": "phase3",
        "candidate_key": row.get("candidate_key"),
        "candidate_type": row.get("candidate_type"),
        "review": row.get("raw_payload", {}),
    }
    if phase_relation:
        payload["phase_relation"] = phase_relation
    return json.dumps(payload, default=str)


def add_sample(
    stats: RegionRelationshipProposalStats,
    item: str,
    sample_size: int,
) -> None:
    if len(stats.sample) < sample_size:
        stats.sample.append(item)
