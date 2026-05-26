"""Phase 2 regional candidate discovery.

This module performs deterministic discovery from Wikipedia categories and
list pages. GPT workers should use the same tables for reviewed additions
rather than writing directly into display graph tables.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mwparserfromhell
import structlog
from sqlalchemy import text

from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_graph import (
    clean_region_name,
    normalize_region_id,
    region_name_from_music_in_title,
    region_name_from_music_title,
)

logger = structlog.get_logger(__name__)

WIKIPEDIA_BASE_URL = "https://en.wikipedia.org/wiki/"
SOURCE_CATEGORY = "wikipedia_category"
SOURCE_LIST = "wikipedia_list"

CATEGORY_SEEDS = (
    "Category:Music by country",
    "Category:Music by continent",
    "Category:Music by region",
    "Category:Music by city",
    "Category:Music by dependent territory",
    "Category:Music of Africa",
    "Category:Music of Asia",
    "Category:Music of Europe",
    "Category:Music of North America",
    "Category:Music of South America",
    "Category:Music of Oceania",
    "Category:Music of the Caribbean",
    "Category:Music of the Caribbean by country",
    "Category:Music of the Caribbean by dependent territory",
    "Category:Music of Latin America",
    "Category:Caribbean music genres",
    "Category:Latin American music genres",
    "Category:Folk music by country",
    "Category:Traditional music",
    "Category:Indigenous music",
    "Category:Music of indigenous peoples",
    "Category:African diaspora music",
    "Category:Music and politics",
    "Category:Ancient music",
    "Category:Medieval music",
    "Category:Renaissance music",
)

LIST_SEEDS = (
    "Lists of music genres",
    "List of Caribbean music genres",
    "List of Caribbean folk music traditions",
    "List of cultural and regional genres of music",
    "List of folk music traditions",
    "List of Latin music genres",
    "List of music genres and styles",
    "List of musical genres of the African diaspora",
    "List of styles of music: A-F",
    "List of styles of music: G-M",
    "List of styles of music: N-R",
    "List of styles of music: S-Z",
)

REGIONAL_TERMS = (
    "african",
    "american",
    "arab",
    "asian",
    "caribbean",
    "celtic",
    "diaspora",
    "european",
    "latin",
    "middle eastern",
    "nordic",
    "pacific",
)

NOISY_CATEGORY_TERMS = (
    "albums",
    "alumni",
    "archive",
    "association football music",
    "award",
    "awards",
    "based on works",
    "by former country",
    "by genre and country",
    "by decade",
    "by year",
    "charts",
    "companies",
    "company",
    "competition",
    "competitions",
    "compositions",
    "conservatoire",
    "conservatorium",
    "documentary films",
    "education",
    "educators",
    "events",
    "festivals",
    "films",
    "folk music groups",
    "houses",
    "hall of fame",
    "industries",
    "industry",
    "instruments",
    "instrument ensembles",
    "instrument makers",
    "journalism",
    "mass media",
    "members of",
    "music association",
    "music magazine",
    "music-related lists",
    "musicologists",
    "musical groups",
    "musical atlas",
    "musical museum",
    "musical theatre",
    "musicals",
    "music magazines",
    "music museum",
    "music museums",
    "music people",
    "music videos",
    "music about",
    "music commissioned by",
    "music competitions",
    "music critics",
    "music festival",
    "music festivals",
    "music manuscript sources",
    "music schools",
    "music society",
    "music theatre",
    "music and politics",
    "music by former country",
    "music by genre and country",
    "music censorship",
    "music mass media",
    "musicology",
    "music duos",
    "music groups",
    "musicians",
    "nightclubs",
    "opera houses",
    "organisations",
    "organizations",
    "political music artists",
    "political music genres",
    "podcasters",
    "artists",
    "patrons of music",
    "performers",
    "printers",
    "radio programs",
    "radio stations",
    "record labels",
    "retailers",
    "symphony orchestra",
    "television series",
    "television shows",
    "theory",
    "school of music",
    "school of folk music",
    "song cycle",
    "songs",
    "stubs",
    "venues",
    "video directors",
    "websites",
    "writers about music",
    "years in",
    "psychological operations",
    "research association",
)

GENERIC_LIST_CONTEXTS = {
    "",
    "by country",
    "by region",
    "by territory",
    "by dependent territory",
    "examples",
    "external links",
    "further reading",
    "genres",
    "notes",
    "references",
    "see also",
    "sources",
    "styles",
}

LIST_ROW_CONTEXT_DELIMITERS = (":", " - ", " – ", " — ")


@dataclass(frozen=True)
class DiscoverySource:
    source_type: str
    source_title: str
    source_url: str | None = None
    parent_key: str | None = None
    depth: int = 0

    @property
    def source_key(self) -> str:
        return stable_key("source", self.source_type, self.source_title)


@dataclass(frozen=True)
class RegionCandidate:
    candidate_type: str
    title: str
    source: DiscoverySource
    normalized_title: str
    suggested_region_id: str | None = None
    suggested_region_name: str | None = None
    source_section: str | None = None
    evidence_text: str | None = None
    confidence: float = 0.5
    status: str = "discovered"
    review_reason: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def candidate_key(self) -> str:
        return stable_key(
            "candidate",
            self.candidate_type,
            self.normalized_title,
            self.source.source_key,
            self.source_section or "",
        )


@dataclass
class RegionDiscoveryStats:
    sources_seeded: int = 0
    sources_processed: int = 0
    sources_failed: int = 0
    category_members_seen: int = 0
    list_links_seen: int = 0
    candidates_found: int = 0
    candidates_upserted: int = 0
    discovered_sources_upserted: int = 0
    dry_run: bool = False
    sample: list[RegionCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RegionReviewExportStats:
    rows_exported: int = 0
    output_path: Path | None = None


@dataclass
class RegionReviewImportStats:
    rows_seen: int = 0
    rows_updated: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class RegionAutoReviewStats:
    rows_seen: int = 0
    rows_updated: int = 0
    accepted: int = 0
    rejected: int = 0
    needs_review: int = 0


@dataclass
class RegionManualReviewStats:
    rows_seen: int = 0
    rows_updated: int = 0
    accepted: int = 0
    rejected: int = 0


@dataclass(frozen=True)
class RegionReviewDecision:
    decision: str
    suggested_region_name: str | None
    suggested_region_kind: str
    confidence: float
    reason: str


def stable_key(*parts: str) -> str:
    digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return digest


def normalize_title(title: str) -> str:
    title = title.replace("_", " ").strip()
    if title.startswith(":"):
        title = title[1:].strip()
    return " ".join(title.split())


def review_payload_from_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return the JSONL shape expected by GPT review workers."""
    return {
        "candidate_key": row["candidate_key"],
        "decision": None,
        "candidate_type": row["candidate_type"],
        "normalized_title": row["normalized_title"],
        "title": row["title"],
        "suggested_region_name": row["suggested_region_name"],
        "suggested_region_kind": "unknown",
        "confidence": row["confidence"],
        "reason": None,
        "evidence": {
            "source_key": row["source_key"],
            "source_title": row["source_title"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "source_section": row["source_section"],
            "source_depth": row.get("source_depth"),
            "evidence_text": row["evidence_text"],
            "evidence_kind": "category_membership"
            if row["source_type"] == SOURCE_CATEGORY
            else "list_link",
        },
    }


def wikipedia_url(title: str) -> str:
    return WIKIPEDIA_BASE_URL + title.replace(" ", "_")


def source_from_title(source_type: str, title: str, *, depth: int = 0) -> DiscoverySource:
    return DiscoverySource(
        source_type=source_type,
        source_title=normalize_title(title),
        source_url=wikipedia_url(normalize_title(title)),
        depth=depth,
    )


def region_name_from_music_in_title(title: str) -> str | None:
    title = re.sub(r"^Category:", "", normalize_title(title), flags=re.IGNORECASE)
    match = re.match(r"^Music in (.+)$", title, flags=re.IGNORECASE)
    return normalize_title(match.group(1)) if match else None


def title_without_category(title: str) -> str:
    return re.sub(r"^Category:", "", normalize_title(title), flags=re.IGNORECASE)


def source_title_without_category(title: str | None) -> str:
    return title_without_category(title or "")


def infer_region_kind(title: str, source_title: str | None = None) -> str:
    clean = title_without_category(title)
    source = source_title_without_category(source_title).lower()
    clean_lower = clean.lower()
    region_name = region_name_from_music_title(clean) or region_name_from_music_in_title(clean)
    region_lower = (region_name or clean).lower()

    if clean_lower.startswith("music in "):
        if any(term in clean_lower for term in ("ancient ", "colonial ", "medieval ")):
            return "historical_region"
        if "by city" in source:
            return "city"
        if "by locality" in source:
            return "subregion"
        if any(
            term in region_lower
            for term in (
                "county",
                "department",
                "province",
                "state",
                "territory",
                "region",
                "metropolitan borough",
                "republic",
            )
        ) or "federal subject" in source:
            return "subregion"
        return "city"
    if any(term in clean_lower for term in ("ancient ", "medieval ", "renaissance ")):
        return "historical_region"
    if "diaspora" in clean_lower:
        return "diaspora_region"
    if "indigenous" in clean_lower:
        return "cultural_region"
    if " by dependent territory" in source or any(
        term in region_lower
        for term in (
            "anguilla",
            "bermuda",
            "british virgin islands",
            "cayman islands",
            "faroe islands",
            "french guiana",
            "french polynesia",
            "greenland",
            "guadeloupe",
            "guam",
            "martinique",
            "mayotte",
            "montserrat",
            "new caledonia",
            "réunion",
            "reunion",
            "tokelau",
            "turks and caicos",
            "virgin islands",
        )
    ):
        return "territory"
    if region_lower in {
        "africa",
        "asia",
        "europe",
        "north america",
        "south america",
        "oceania",
    }:
        return "continent"
    if any(
        term in source
        for term in (
            "by country",
            "music by country",
            "music of africa by country",
            "music of asia by country",
            "music of europe by country",
            "music of north america by country",
            "music of south america by country",
        )
    ):
        return "country"
    if any(term in source for term in ("by state", "by province", "by region", "by territory")):
        return "subregion"
    if any(
        term in region_lower
        for term in (
            "caribbean",
            "latin america",
            "middle east",
            "balkans",
            "caucasus",
            "southeast asia",
            "south asia",
            "west africa",
            "central africa",
            "southern africa",
            "east africa",
            "micronesia",
            "polynesia",
            "melanesia",
        )
    ):
        return "subregion"
    return "unknown"


def is_container_title(title: str) -> bool:
    clean = title_without_category(title).lower()
    return bool(
        re.search(
            r"\bby (city|country|continent|dependent territory|locality|province|region|state|territory)\b",
            clean,
        )
    )


def infer_music_region_name(title: str) -> str | None:
    clean = title_without_category(title)
    return region_name_from_music_title(clean) or region_name_from_music_in_title(clean)


def auto_review_candidate_payload(row: dict[str, Any]) -> RegionReviewDecision:
    title = row["title"]
    clean = title_without_category(title)
    lower = clean.lower()
    source_title = row.get("source_title")
    source_lower = source_title_without_category(source_title).lower()
    candidate_type = row["candidate_type"]
    suggested_region_name = row.get("suggested_region_name") or infer_music_region_name(title)

    if any(term in lower for term in NOISY_CATEGORY_TERMS):
        return RegionReviewDecision(
            "reject",
            suggested_region_name,
            "unknown",
            0.96,
            "Deterministic support/admin/media category rejection.",
        )

    if is_container_title(title):
        return RegionReviewDecision(
            "needs_review",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.6),
            "Hierarchy/container category; preserve for Phase 3 relationship review.",
        )

    if candidate_type in {
        "music_region_page",
        "traditional_music_page",
        "indigenous_music_page",
        "historical_music_page",
    }:
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.88),
            "Deterministic high-confidence music region/tradition page.",
        )

    if candidate_type == "music_region_category":
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.88),
            "Deterministic explicit Music of/Music in regional category.",
        )

    if candidate_type == "region_container_category":
        return RegionReviewDecision(
            "needs_review",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.72),
            "Container category; preserve for Phase 3 hierarchy extraction.",
        )

    if candidate_type == "regional_music_list":
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.82),
            "Regional music list source accepted for Phase 3 evidence extraction.",
        )

    if candidate_type in {"cultural_region_page", "diaspora_region_page"}:
        return RegionReviewDecision(
            "needs_review",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.7),
            "Cultural/diaspora music candidate needs relationship review before promotion.",
        )

    if candidate_type == "regional_genre_page":
        if any(
            term in lower
            for term in (
                "folk music",
                "traditional music",
                "indigenous",
                "diaspora",
                "ancient",
                "medieval",
                "renaissance",
            )
        ) or any(
            term in source_lower
            for term in (
                "styles of music",
                "music genres",
                "folk music",
                "traditional music",
                "indigenous music",
            )
        ):
            return RegionReviewDecision(
                "accept",
                suggested_region_name,
                infer_region_kind(title, source_title),
                max(float(row["confidence"]), 0.74),
                "Regional genre/style candidate from regional music evidence.",
            )
        return RegionReviewDecision(
            "needs_review",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.58),
            "Potential regional genre/style needs review.",
        )

    if candidate_type == "unknown_music_candidate":
        if re.match(r"^music history of ", lower) or re.match(r"^classical music in ", lower):
            return RegionReviewDecision(
                "needs_review",
                suggested_region_name,
                infer_region_kind(title, source_title),
                max(float(row["confidence"]), 0.62),
                "Regional history/classical music candidate preserved for review.",
            )
        if any(
            term in lower
            for term in (
                "folk music",
                "traditional music",
                "indigenous",
                "diaspora",
                " music",
            )
        ) and any(
            term in source_lower
            for term in (
                "styles of music",
                "music genres",
                "folk music",
                "traditional music",
                "indigenous music",
                "music of ",
                "music in ",
                "music by region",
                "music by city",
            )
        ):
            return RegionReviewDecision(
                "needs_review",
                suggested_region_name,
                infer_region_kind(title, source_title),
                max(float(row["confidence"]), 0.62),
                "Ambiguous regional music candidate preserved for review.",
            )

    return RegionReviewDecision(
        "needs_review",
        suggested_region_name,
        infer_region_kind(title, source_title),
        max(float(row["confidence"]), 0.5),
        "Conservative fallback; insufficient evidence for deterministic accept/reject.",
    )


MANUAL_REVIEW_REJECT_TERMS = (
    "appreciation month",
    "ballet school",
    "camp",
    "centre for",
    "college",
    "collection",
    "conference",
    "congress",
    "conservatory",
    "library",
    "lyceum",
    "medal",
    "medals",
    "music centre",
    "music center",
    "music union",
    "musical society",
    "performing arts",
    "prize",
    "sculpture",
    "state music",
    "university",
)


def manual_review_candidate_payload(row: dict[str, Any]) -> RegionReviewDecision:
    """Resolve remaining Phase 2 rows with explicit manual-review policy.

    At this point rows have already passed conservative automatic review and
    sampled GPT review. The manual pass keeps musically plausible regional,
    cultural, historical, and style candidates for Phase 3 staging, while
    rejecting support institutions, media artifacts, organizations, awards, and
    other non-relationship pages.
    """
    title = row["title"]
    clean = title_without_category(title)
    lower = clean.lower()
    source_title = row.get("source_title")
    suggested_region_name = row.get("suggested_region_name") or infer_music_region_name(title)

    if any(term in lower for term in NOISY_CATEGORY_TERMS + MANUAL_REVIEW_REJECT_TERMS):
        return RegionReviewDecision(
            "reject",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.9),
            "Manual review rejection: support/admin/media/institution artifact, not a regional music relationship node.",
        )

    if lower.startswith(("timeline of ", "the music of ")):
        return RegionReviewDecision(
            "reject",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.86),
            "Manual review rejection: documentary/list artifact, not a reusable regional genre or region node.",
        )

    if re.match(r"^.+\s+\(\d{4}[-–]\d{4}\)$", clean):
        return RegionReviewDecision(
            "reject",
            suggested_region_name,
            "unknown",
            max(float(row["confidence"]), 0.82),
            "Manual review rejection: period bucket page, not a stable regional music node.",
        )

    candidate_type = row["candidate_type"]
    if candidate_type == "region_container_category":
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.78),
            "Manual review accepted container for Phase 3 hierarchy extraction.",
        )

    if candidate_type == "music_region_category":
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.82),
            "Manual review accepted regional music category for Phase 3 relationship extraction.",
        )

    if candidate_type == "cultural_region_page":
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            infer_region_kind(title, source_title),
            max(float(row["confidence"]), 0.76),
            "Manual review accepted cultural/regional music candidate for Phase 3 staging.",
        )

    if candidate_type == "unknown_music_candidate":
        kind = infer_region_kind(title, source_title)
        if re.match(r"^(music history of|classical music in|history of music in) ", lower):
            kind = "historical_region"
        return RegionReviewDecision(
            "accept",
            suggested_region_name,
            kind,
            max(float(row["confidence"]), 0.7),
            "Manual review accepted ambiguous music candidate for staged Phase 3 relationship extraction.",
        )

    return RegionReviewDecision(
        "accept",
        suggested_region_name,
        infer_region_kind(title, source_title),
        max(float(row["confidence"]), 0.72),
        "Manual review accepted plausible regional genre/style candidate for Phase 3 staging.",
    )


def classify_candidate_title(title: str, *, namespace: int | None = None) -> tuple[str, str, float]:
    """Return candidate_type, status, confidence for a Wikipedia title."""
    normalized = normalize_title(title)
    lower = normalized.lower()
    without_category = re.sub(r"^category:", "", normalized, flags=re.IGNORECASE)
    without_category_lower = without_category.lower()
    is_explicit_music_region = without_category_lower.startswith("music of ")
    is_explicit_music_in_region = without_category_lower.startswith("music in ")
    is_year_bucket = bool(
        re.match(r"^\d{4} in .+ music$", without_category_lower)
        or re.match(r"^\d+(st|nd|rd|th) century in music$", without_category_lower)
    )

    if namespace == 14 or lower.startswith("category:"):
        if is_year_bucket:
            return "unknown_music_candidate", "rejected", 0.1
        if not (is_explicit_music_region or is_explicit_music_in_region) and any(
            term in without_category_lower for term in NOISY_CATEGORY_TERMS
        ):
            return "unknown_music_candidate", "rejected", 0.1
        if is_explicit_music_region or is_explicit_music_in_region:
            return "music_region_category", "needs_gpt_review", 0.76
        if " by country" in without_category_lower or " by dependent territory" in without_category_lower:
            return "region_container_category", "needs_gpt_review", 0.72
        if (
            without_category_lower.endswith(" folk music")
            or without_category_lower.endswith(" traditional music")
            or " styles of music" in without_category_lower
        ):
            return "regional_genre_page", "needs_gpt_review", 0.5
        if "music" in without_category_lower and any(
            term in without_category_lower for term in REGIONAL_TERMS
        ):
            return "cultural_region_page", "needs_gpt_review", 0.58
        if "music" in without_category_lower:
            return "unknown_music_candidate", "needs_gpt_review", 0.42
        return "unknown_music_candidate", "rejected", 0.1

    if is_year_bucket:
        return "unknown_music_candidate", "rejected", 0.1
    if any(term in lower for term in NOISY_CATEGORY_TERMS) and not region_name_from_music_title(
        normalized
    ):
        return "unknown_music_candidate", "rejected", 0.1

    if lower.startswith(("list of ", "lists of ")) and "music" in lower:
        return "regional_music_list", "needs_gpt_review", 0.7
    if region_name_from_music_title(normalized) or region_name_from_music_in_title(normalized):
        return "music_region_page", "discovered", 0.88
    if lower.startswith("music in ancient ") or lower.startswith("music of ancient "):
        return "historical_music_page", "discovered", 0.82
    if lower.startswith("traditional music of ") or " traditional music" in lower:
        return "traditional_music_page", "discovered", 0.78
    if lower.startswith("indigenous music") or re.search(r"\bindigenous\b.*\bmusic\b", lower):
        return "indigenous_music_page", "discovered", 0.78
    if any(term in lower for term in ("ancient music", "medieval music", "renaissance music")):
        return "historical_music_page", "discovered", 0.76
    if "diaspora" in lower and "music" in lower:
        return "diaspora_region_page", "needs_gpt_review", 0.7
    if any(term in lower for term in REGIONAL_TERMS) and "music" in lower:
        return "cultural_region_page", "needs_gpt_review", 0.58
    if "music" in lower:
        return "regional_genre_page", "needs_gpt_review", 0.46
    return "unknown_music_candidate", "rejected", 0.1


def candidate_from_title(
    title: str,
    source: DiscoverySource,
    *,
    namespace: int | None = None,
    source_section: str | None = None,
    evidence_text: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> RegionCandidate | None:
    normalized = normalize_title(title)
    if not normalized or normalized.startswith(("File:", "Help:", "Template:", "Wikipedia:")):
        return None
    candidate_type, status, confidence = classify_candidate_title(normalized, namespace=namespace)
    if status == "rejected":
        return None

    region_name = region_name_from_music_title(normalized)
    if not region_name:
        region_name = region_name_from_music_in_title(normalized)
    if not region_name and candidate_type == "music_region_category":
        region_name = region_name_from_music_title(re.sub(r"^Category:", "", normalized))
        if not region_name:
            region_name = region_name_from_music_in_title(re.sub(r"^Category:", "", normalized))

    return RegionCandidate(
        candidate_type=candidate_type,
        title=normalized,
        normalized_title=normalized.lower(),
        suggested_region_id=normalize_region_id(region_name) if region_name else None,
        suggested_region_name=region_name,
        source=source,
        source_section=source_section,
        evidence_text=evidence_text or normalized,
        confidence=confidence,
        status=status,
        review_reason=("heuristic_needs_review" if status == "needs_gpt_review" else None),
        raw_payload=raw_payload or {},
    )


def _strip_wikitext(text: str) -> str:
    return normalize_title(mwparserfromhell.parse(text).strip_code())


def _clean_list_context(text: str | None) -> str | None:
    if not text:
        return None
    clean = _strip_wikitext(text)
    clean = re.sub(r"^[*#:;|\s!]+", "", clean).strip()
    clean = re.sub(r"\s+", " ", clean).strip(" -–—:;,.")
    if not clean:
        return None
    lower = clean.lower()
    if lower in GENERIC_LIST_CONTEXTS or lower.startswith("by "):
        return None
    if len(clean) > 80 or len(clean.split()) > 8:
        return None
    if any(term in lower for term in ("genre", "style", "tradition", "references")):
        return None
    if lower.startswith(("list of ", "category:", "file:", "template:", "wikipedia:")):
        return None
    return clean


def _context_from_wikilink_target(target: str | None) -> str | None:
    if not target:
        return None
    clean = normalize_title(str(target).split("#", 1)[0])
    if not clean or ":" in clean:
        return None
    return (
        region_name_from_music_title(clean)
        or region_name_from_music_in_title(clean)
        or _clean_list_context(clean)
    )


def _first_context_from_markup(markup: str) -> str | None:
    wikicode = mwparserfromhell.parse(markup)
    links = wikicode.filter_wikilinks()
    if links:
        context = _context_from_wikilink_target(str(links[0].title))
        if context:
            return context
        if links[0].text is not None:
            context = _clean_list_context(str(links[0].text))
            if context:
                return context
    return _clean_list_context(markup)


def _nearest_list_context(context_by_depth: dict[int, str], depth: int) -> str | None:
    for candidate_depth in range(depth, 0, -1):
        context = context_by_depth.get(candidate_depth)
        if context:
            return context
    return None


def _is_known_list_context(context: str | None, known_region_names: set[str] | None) -> bool:
    if not context or known_region_names is None:
        return bool(context)
    clean = clean_region_name(context) or context
    return clean.lower() in known_region_names


def _split_contextual_list_line(
    line: str,
    *,
    known_region_names: set[str] | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    stripped = line.strip()
    if not stripped:
        return None, None, None, None

    if stripped.startswith("|") and "||" in stripped:
        cells = [cell.strip() for cell in stripped.lstrip("|").split("||")]
        if len(cells) >= 2:
            context = _first_context_from_markup(cells[0])
            if _is_known_list_context(context, known_region_names):
                return context, cells[0], " ".join(cells[1:]), "table_row"

    if stripped.startswith(";") and ":" in stripped:
        context_markup, content_markup = stripped[1:].split(":", 1)
        context = _first_context_from_markup(context_markup)
        if _is_known_list_context(context, known_region_names):
            return context, context_markup, content_markup, "definition_row"

    if not re.match(r"^[*#]+", stripped):
        return None, None, None, None

    item = re.sub(r"^[*#;:]+\s*", "", stripped)
    for delimiter in LIST_ROW_CONTEXT_DELIMITERS:
        if delimiter not in item:
            continue
        context_markup, content_markup = item.split(delimiter, 1)
        if "[[" not in content_markup:
            continue
        context = _first_context_from_markup(context_markup)
        if _is_known_list_context(context, known_region_names):
            return context, context_markup, content_markup, "inline_context_row"

    return None, None, None, None


def _is_same_context_link(title: str, context_region: str | None) -> bool:
    if not context_region:
        return False
    context = _clean_list_context(context_region)
    target_context = _context_from_wikilink_target(title)
    return bool(context and target_context and context.lower() == target_context.lower())


def _forced_list_genre_candidate(
    title: str,
    source: DiscoverySource,
    *,
    context_region: str,
    evidence_text: str,
    raw_payload: dict[str, Any],
) -> RegionCandidate | None:
    normalized = normalize_title(str(title).split("#", 1)[0])
    if not normalized or ":" in normalized:
        return None
    if _is_same_context_link(normalized, context_region):
        return None
    if region_name_from_music_title(normalized) or region_name_from_music_in_title(normalized):
        return candidate_from_title(
            normalized,
            source,
            source_section=context_region,
            evidence_text=evidence_text,
            raw_payload=raw_payload,
        )
    return RegionCandidate(
        candidate_type="regional_genre_page",
        title=normalized,
        normalized_title=normalized.lower(),
        source=source,
        source_section=context_region,
        evidence_text=evidence_text,
        confidence=0.56,
        status="needs_gpt_review",
        review_reason="semantic_list_row_context",
        raw_payload=raw_payload,
    )


def _candidates_from_list_markup(
    markup: str,
    source: DiscoverySource,
    *,
    current_section: str | None,
    context_region: str | None,
    row_type: str,
    line_number: int,
) -> list[RegionCandidate]:
    wikicode = mwparserfromhell.parse(markup)
    evidence_text = normalize_title(wikicode.strip_code())[:500]
    candidates: list[RegionCandidate] = []
    seen_titles: set[str] = set()
    for link in wikicode.filter_wikilinks():
        target = normalize_title(str(link.title).split("#", 1)[0])
        if not target or ":" in target or target in seen_titles:
            continue
        seen_titles.add(target)
        payload = {
            "list_section": current_section,
            "list_context_region": context_region,
            "list_row_type": row_type,
            "list_line_number": line_number,
        }
        target_is_music_region = bool(
            region_name_from_music_title(target) or region_name_from_music_in_title(target)
        )
        if context_region and _is_same_context_link(target, context_region) and not target_is_music_region:
            continue
        candidate = candidate_from_title(
            target,
            source,
            source_section=context_region or current_section,
            evidence_text=evidence_text,
            raw_payload=payload,
        )
        if not candidate and context_region:
            candidate = _forced_list_genre_candidate(
                target,
                source,
                context_region=context_region,
                evidence_text=evidence_text,
                raw_payload=payload,
            )
        if candidate:
            candidates.append(candidate)
    return candidates


def category_source_from_member(
    member_title: str,
    *,
    parent: DiscoverySource,
    namespace: int | None,
) -> DiscoverySource | None:
    if namespace != 14:
        return None
    title = normalize_title(member_title)
    if not title.lower().startswith("category:"):
        title = f"Category:{title}"
    candidate_type, status, _confidence = classify_candidate_title(title, namespace=14)
    if status == "rejected" or candidate_type == "unknown_music_candidate":
        return None
    return DiscoverySource(
        source_type=SOURCE_CATEGORY,
        source_title=title,
        source_url=wikipedia_url(title),
        parent_key=parent.source_key,
        depth=parent.depth + 1,
    )


def extract_list_candidates(
    wikitext: str,
    source: DiscoverySource,
    *,
    known_region_names: set[str] | None = None,
) -> list[RegionCandidate]:
    candidates: list[RegionCandidate] = []
    current_section: str | None = None
    context_by_depth: dict[int, str] = {}
    in_table = False
    for line_number, line in enumerate(wikitext.splitlines(), start=1):
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith(("<!--", "{{", "}}"))
            or stripped.startswith("|") and not in_table
            or "<ref" in stripped.lower()
            or "{{cite" in stripped.lower()
            or "http://" in stripped.lower()
            or "https://" in stripped.lower()
            or "//www." in stripped.lower()
            or stripped.lower().startswith(("url=", "|url=", "title=", "|title="))
        ):
            continue
        heading = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", line)
        if heading:
            current_section = normalize_title(mwparserfromhell.parse(heading.group(2)).strip_code())
            context_by_depth.clear()
            continue

        if stripped.startswith("{|"):
            in_table = True
            continue
        if stripped.startswith("|}"):
            in_table = False
            continue
        if stripped.startswith("|-") or stripped.startswith("!"):
            continue

        row_context, context_markup, content_markup, row_type = _split_contextual_list_line(
            line,
            known_region_names=known_region_names,
        )
        if row_context and row_type:
            depth = len(re.match(r"^([*#]+)", stripped).group(1)) if re.match(r"^([*#]+)", stripped) else 1
            context_by_depth[depth] = row_context
            if "[[" in (content_markup or ""):
                candidates.extend(
                    _candidates_from_list_markup(
                        content_markup or "",
                        source,
                        current_section=current_section,
                        context_region=row_context,
                        row_type=row_type,
                        line_number=line_number,
                    )
                )
                continue

        if "[[" not in line:
            maybe_context = _clean_list_context(line) if re.match(r"^[*#]+", stripped) else None
            if _is_known_list_context(maybe_context, known_region_names):
                depth = len(re.match(r"^([*#]+)", stripped).group(1))
                context_by_depth[depth] = maybe_context
            continue

        depth = len(re.match(r"^([*#]+)", stripped).group(1)) if re.match(r"^([*#]+)", stripped) else 0
        inherited_context = _nearest_list_context(context_by_depth, max(depth - 1, 0))
        section_context = _clean_list_context(current_section)
        if not _is_known_list_context(section_context, known_region_names):
            section_context = None
        context_region = inherited_context or section_context

        line_candidates = _candidates_from_list_markup(
            line,
            source,
            current_section=current_section,
            context_region=context_region,
            row_type="table_line" if in_table else "section_or_nested_line",
            line_number=line_number,
        )
        candidates.extend(line_candidates)

        if depth and len(line_candidates) == 1:
            only = line_candidates[0]
            candidate_context = (
                only.suggested_region_name
                if only.candidate_type in {"music_region_page", "music_region_category"}
                else None
            )
            if candidate_context:
                context_by_depth[depth] = candidate_context
            else:
                context = _first_context_from_markup(line)
                if _is_known_list_context(context, known_region_names):
                    context_by_depth[depth] = context
        elif depth and not line_candidates:
            context = _first_context_from_markup(line)
            if _is_known_list_context(context, known_region_names):
                context_by_depth[depth] = context

    return candidates


async def seed_region_discovery_sources() -> int:
    await apply_migrations()
    sources = [
        *(source_from_title(SOURCE_CATEGORY, title) for title in CATEGORY_SEEDS),
        *(source_from_title(SOURCE_LIST, title) for title in LIST_SEEDS),
    ]
    engine = get_engine()
    async with engine.begin() as conn:
        await _upsert_sources(conn, sources)
    return len(sources)


async def reset_region_discovery() -> None:
    """Clear Phase 2 candidate discovery tables."""
    await apply_migrations()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM wg_region_candidate_relationships"))
        await conn.execute(text("DELETE FROM wg_region_candidates"))
        await conn.execute(text("DELETE FROM wg_region_discovery_sources"))


async def export_region_review_batch(
    output_path: Path,
    *,
    limit: int = 200,
    candidate_type: str | None = None,
    source_type: str | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    status: str = "needs_gpt_review",
) -> RegionReviewExportStats:
    """Export reviewable candidate rows as JSONL for GPT workers."""
    await apply_migrations()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filters = ["c.status = :status"]
    params: dict[str, Any] = {"status": status, "limit": limit}
    if candidate_type:
        filters.append("c.candidate_type = :candidate_type")
        params["candidate_type"] = candidate_type
    if source_type:
        filters.append("c.source_type = :source_type")
        params["source_type"] = source_type
    if min_confidence is not None:
        filters.append("c.confidence >= :min_confidence")
        params["min_confidence"] = min_confidence
    if max_confidence is not None:
        filters.append("c.confidence <= :max_confidence")
        params["max_confidence"] = max_confidence

    engine = get_engine()
    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text(f"""
                        SELECT
                            c.candidate_key,
                            c.candidate_type,
                            c.title,
                            c.normalized_title,
                            c.suggested_region_name,
                            c.source_key,
                            c.source_type,
                            c.source_title,
                            c.source_url,
                            c.source_section,
                            c.evidence_text,
                            c.confidence,
                            s.depth AS source_depth
                        FROM wg_region_candidates c
                        LEFT JOIN wg_region_discovery_sources s
                          ON s.source_key = c.source_key
                        WHERE {" AND ".join(filters)}
                        ORDER BY
                            CASE c.candidate_type
                                WHEN 'music_region_category' THEN 0
                                WHEN 'regional_genre_page' THEN 1
                                WHEN 'cultural_region_page' THEN 2
                                WHEN 'regional_music_list' THEN 3
                                WHEN 'unknown_music_candidate' THEN 4
                                ELSE 5
                            END,
                            s.depth NULLS LAST,
                            c.confidence DESC,
                            c.normalized_title
                        LIMIT :limit
                    """),
                    params,
                )
            )
            .mappings()
            .fetchall()
        )

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(review_payload_from_candidate_row(dict(row)), sort_keys=True))
            handle.write("\n")

    return RegionReviewExportStats(rows_exported=len(rows), output_path=output_path)


async def import_region_review_batch(input_path: Path) -> RegionReviewImportStats:
    """Apply GPT worker JSONL decisions back to candidate staging rows."""
    await apply_migrations()
    stats = RegionReviewImportStats()
    allowed_decisions = {"accept": "accepted", "reject": "rejected", "needs_review": "needs_gpt_review"}
    allowed_kinds = {
        "country",
        "territory",
        "city",
        "subregion",
        "continent",
        "cultural_region",
        "diaspora_region",
        "historical_region",
        "language_region",
        "unknown",
    }
    engine = get_engine()
    async with engine.begin() as conn:
        with input_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                stats.rows_seen += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    stats.errors.append(f"line {line_number}: invalid JSON: {exc}")
                    continue
                candidate_key = payload.get("candidate_key")
                decision = payload.get("decision")
                if not candidate_key or decision not in allowed_decisions:
                    stats.errors.append(f"line {line_number}: missing candidate_key or bad decision")
                    continue
                suggested_kind = payload.get("suggested_region_kind") or "unknown"
                if suggested_kind not in allowed_kinds:
                    stats.errors.append(f"line {line_number}: bad suggested_region_kind")
                    continue
                confidence = payload.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    stats.errors.append(f"line {line_number}: bad confidence")
                    continue
                confidence = min(1.0, max(0.0, confidence))

                result = await conn.execute(
                    text("""
                        UPDATE wg_region_candidates
                        SET status = :status,
                            confidence = :confidence,
                            suggested_region_name = COALESCE(
                                :suggested_region_name,
                                suggested_region_name
                            ),
                            suggested_region_id = COALESCE(
                                :suggested_region_id,
                                suggested_region_id
                            ),
                            review_reason = :review_reason,
                            extractor_model = :extractor_model,
                            raw_payload = raw_payload || CAST(:review_payload AS jsonb),
                            updated_at = now()
                        WHERE candidate_key = :candidate_key
                    """),
                    {
                        "candidate_key": candidate_key,
                        "status": allowed_decisions[decision],
                        "confidence": confidence,
                        "suggested_region_name": payload.get("suggested_region_name"),
                        "suggested_region_id": (
                            normalize_region_id(payload["suggested_region_name"])
                            if payload.get("suggested_region_name")
                            else None
                        ),
                        "review_reason": payload.get("reason"),
                        "extractor_model": payload.get("model") or "gpt-5.4-mini",
                        "review_payload": json.dumps(
                            {
                                "gpt_review": {
                                    "decision": decision,
                                    "candidate_type": payload.get("candidate_type"),
                                    "suggested_region_kind": suggested_kind,
                                    "reason": payload.get("reason"),
                                    "evidence": payload.get("evidence"),
                                }
                            }
                        ),
                    },
                )
                if result.rowcount:
                    stats.rows_updated += result.rowcount
                else:
                    stats.rows_rejected += 1
                    stats.errors.append(f"line {line_number}: candidate not found")
    return stats


async def auto_review_region_candidates(
    *,
    include_existing_reviewed: bool = False,
) -> RegionAutoReviewStats:
    """Conservatively triage all remaining Phase 2 candidates."""
    await apply_migrations()
    stats = RegionAutoReviewStats()
    status_map = {"accept": "accepted", "reject": "rejected", "needs_review": "needs_gpt_review"}
    engine = get_engine()
    async with engine.begin() as conn:
        reviewed_filter = "" if include_existing_reviewed else "WHERE NOT (raw_payload ? 'gpt_review')"
        rows = (
            (
                await conn.execute(
                    text(f"""
                        SELECT
                            candidate_key,
                            candidate_type,
                            title,
                            normalized_title,
                            suggested_region_name,
                            source_key,
                            source_type,
                            source_title,
                            source_url,
                            source_section,
                            evidence_text,
                            confidence
                        FROM wg_region_candidates
                        {reviewed_filter}
                        ORDER BY candidate_type, normalized_title, source_title
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.rows_seen = len(rows)
        for row in rows:
            row_dict = dict(row)
            decision = auto_review_candidate_payload(row_dict)
            if decision.decision == "accept":
                stats.accepted += 1
            elif decision.decision == "reject":
                stats.rejected += 1
            else:
                stats.needs_review += 1

            result = await conn.execute(
                text("""
                    UPDATE wg_region_candidates
                    SET status = :status,
                        confidence = greatest(confidence, :confidence),
                        suggested_region_name = COALESCE(:suggested_region_name, suggested_region_name),
                        suggested_region_id = COALESCE(:suggested_region_id, suggested_region_id),
                        review_reason = :review_reason,
                        extractor_model = :extractor_model,
                        raw_payload = raw_payload || CAST(:review_payload AS jsonb),
                        updated_at = now()
                    WHERE candidate_key = :candidate_key
                """),
                {
                    "candidate_key": row_dict["candidate_key"],
                    "status": status_map[decision.decision],
                    "confidence": decision.confidence,
                    "suggested_region_name": decision.suggested_region_name,
                    "suggested_region_id": (
                        normalize_region_id(decision.suggested_region_name)
                        if decision.suggested_region_name
                        else None
                    ),
                    "review_reason": decision.reason,
                    "extractor_model": "deterministic-region-review-v1",
                    "review_payload": json.dumps(
                        {
                            "gpt_review": {
                                "decision": decision.decision,
                                "candidate_type": row_dict["candidate_type"],
                                "suggested_region_kind": decision.suggested_region_kind,
                                "reason": decision.reason,
                                "evidence": review_payload_from_candidate_row(row_dict)["evidence"],
                            }
                        }
                    ),
                },
            )
            stats.rows_updated += result.rowcount or 0
    return stats


async def finalize_region_candidate_reviews() -> RegionManualReviewStats:
    """Resolve all remaining ``needs_gpt_review`` rows with manual policy."""
    await apply_migrations()
    stats = RegionManualReviewStats()
    status_map = {"accept": "accepted", "reject": "rejected"}
    engine = get_engine()
    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            candidate_key,
                            candidate_type,
                            title,
                            normalized_title,
                            suggested_region_name,
                            source_key,
                            source_type,
                            source_title,
                            source_url,
                            source_section,
                            evidence_text,
                            confidence
                        FROM wg_region_candidates
                        WHERE status = 'needs_gpt_review'
                        ORDER BY candidate_type, normalized_title, source_title
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.rows_seen = len(rows)
        for row in rows:
            row_dict = dict(row)
            decision = manual_review_candidate_payload(row_dict)
            if decision.decision == "reject":
                stats.rejected += 1
            else:
                stats.accepted += 1

            result = await conn.execute(
                text("""
                    UPDATE wg_region_candidates
                    SET status = :status,
                        confidence = greatest(confidence, :confidence),
                        suggested_region_name = COALESCE(:suggested_region_name, suggested_region_name),
                        suggested_region_id = COALESCE(:suggested_region_id, suggested_region_id),
                        review_reason = :review_reason,
                        extractor_model = :extractor_model,
                        raw_payload = raw_payload || CAST(:review_payload AS jsonb),
                        updated_at = now()
                    WHERE candidate_key = :candidate_key
                """),
                {
                    "candidate_key": row_dict["candidate_key"],
                    "status": status_map[decision.decision],
                    "confidence": decision.confidence,
                    "suggested_region_name": decision.suggested_region_name,
                    "suggested_region_id": (
                        normalize_region_id(decision.suggested_region_name)
                        if decision.suggested_region_name
                        else None
                    ),
                    "review_reason": decision.reason,
                    "extractor_model": "manual-region-review-v1",
                    "review_payload": json.dumps(
                        {
                            "manual_review": {
                                "decision": decision.decision,
                                "candidate_type": row_dict["candidate_type"],
                                "suggested_region_kind": decision.suggested_region_kind,
                                "reason": decision.reason,
                                "evidence": review_payload_from_candidate_row(row_dict)["evidence"],
                            }
                        }
                    ),
                },
            )
            stats.rows_updated += result.rowcount or 0
    return stats


async def discover_region_candidates(
    *,
    dry_run: bool = False,
    from_cache: bool = False,
    max_category_depth: int = 2,
    max_sources: int | None = None,
    max_category_pages: int = 3,
    sample_size: int = 25,
) -> RegionDiscoveryStats:
    """Discover regional candidate pages from seeded category and list sources."""
    await apply_migrations()
    stats = RegionDiscoveryStats(dry_run=dry_run)
    stats.sources_seeded = await seed_region_discovery_sources()
    fetcher = WikiFetcher(from_cache=from_cache)
    engine = get_engine()
    known_region_names = await _load_known_region_context_names(engine)

    try:
        processed_keys: set[str] = set()
        while max_sources is None or stats.sources_processed < max_sources:
            async with engine.begin() as conn:
                remaining_limit = (
                    min(50, max_sources - stats.sources_processed)
                    if max_sources is not None
                    else 50
                )
                source_rows = (
                    (
                        await conn.execute(
                            text("""
                        SELECT source_key, source_type, source_title, source_url, parent_key, depth
                        FROM wg_region_discovery_sources
                        WHERE source_type IN (:category_source, :list_source)
                          AND status = 'pending'
                          AND depth <= :max_category_depth
                        ORDER BY depth, source_type, source_title
                        LIMIT :limit
                    """),
                            {
                                "category_source": SOURCE_CATEGORY,
                                "list_source": SOURCE_LIST,
                                "max_category_depth": max_category_depth,
                                "limit": remaining_limit,
                            },
                        )
                    )
                    .mappings()
                    .fetchall()
                )
            if not source_rows:
                break

            for row in source_rows:
                if row["source_key"] in processed_keys:
                    await _mark_source_status(
                        DiscoverySource(
                            source_type=row["source_type"],
                            source_title=row["source_title"],
                            source_url=row["source_url"],
                            parent_key=row["parent_key"],
                            depth=row["depth"],
                        ),
                        "skipped",
                    )
                    continue
                processed_keys.add(row["source_key"])
                await _process_source_row(
                    row,
                    fetcher=fetcher,
                    engine=engine,
                    dry_run=dry_run,
                    max_category_depth=max_category_depth,
                    max_category_pages=max_category_pages,
                    known_region_names=known_region_names,
                    sample_size=sample_size,
                    stats=stats,
                )

    finally:
        await fetcher.aclose()

    logger.info(
        "region_discovery_complete",
        sources_processed=stats.sources_processed,
        sources_failed=stats.sources_failed,
        candidates_found=stats.candidates_found,
        candidates_upserted=stats.candidates_upserted,
        discovered_sources_upserted=stats.discovered_sources_upserted,
    )
    return stats


async def _process_source_row(
    row,
    *,
    fetcher: WikiFetcher,
    engine,
    dry_run: bool,
    max_category_depth: int,
    max_category_pages: int,
    known_region_names: set[str],
    sample_size: int,
    stats: RegionDiscoveryStats,
) -> None:
    source = DiscoverySource(
        source_type=row["source_type"],
        source_title=row["source_title"],
        source_url=row["source_url"],
        parent_key=row["parent_key"],
        depth=row["depth"],
    )
    try:
        candidates, discovered_sources = await _discover_from_source(
            fetcher,
            source,
            max_category_depth=max_category_depth,
            max_category_pages=max_category_pages,
            known_region_names=known_region_names,
            stats=stats,
        )
    except Exception as exc:  # noqa: BLE001
        stats.sources_failed += 1
        stats.errors.append(f"{source.source_title}: {exc}")
        await _mark_source_status(source, "failed")
        return

    stats.sources_processed += 1
    stats.candidates_found += len(candidates)
    if len(stats.sample) < sample_size:
        stats.sample.extend(candidates[: sample_size - len(stats.sample)])

    if dry_run:
        return

    async with engine.begin() as conn:
        if discovered_sources:
            await _upsert_sources(conn, discovered_sources)
            stats.discovered_sources_upserted += len(discovered_sources)
        if candidates:
            await _upsert_candidates(conn, candidates)
            stats.candidates_upserted += len(candidates)
        await _mark_source_status(source, "fetched", conn=conn)


async def _discover_from_source(
    fetcher: WikiFetcher,
    source: DiscoverySource,
    *,
    max_category_depth: int,
    max_category_pages: int,
    known_region_names: set[str],
    stats: RegionDiscoveryStats,
) -> tuple[list[RegionCandidate], list[DiscoverySource]]:
    if source.source_type == SOURCE_CATEGORY:
        return await _discover_from_category(
            fetcher,
            source,
            max_category_depth=max_category_depth,
            max_category_pages=max_category_pages,
            stats=stats,
        )
    if source.source_type == SOURCE_LIST:
        return await _discover_from_list(
            fetcher,
            source,
            known_region_names=known_region_names,
            stats=stats,
        ), []
    return [], []


async def _discover_from_category(
    fetcher: WikiFetcher,
    source: DiscoverySource,
    *,
    max_category_depth: int,
    max_category_pages: int,
    stats: RegionDiscoveryStats,
) -> tuple[list[RegionCandidate], list[DiscoverySource]]:
    candidates: list[RegionCandidate] = []
    discovered_sources: list[DiscoverySource] = []
    cmcontinue: str | None = None
    pages_seen = 0
    while pages_seen < max_category_pages:
        result = await fetcher.fetch_category_members(source.source_title, cmcontinue=cmcontinue)
        if not result.ok:
            raise RuntimeError(f"category fetch failed: HTTP {result.http_status}")
        data = result.json()
        members = data.get("query", {}).get("categorymembers", [])
        stats.category_members_seen += len(members)
        for member in members:
            title = normalize_title(member.get("title", ""))
            namespace = member.get("ns")
            candidate = candidate_from_title(
                title,
                source,
                namespace=namespace,
                evidence_text=f"{title} is a member of {source.source_title}.",
                raw_payload={"pageid": member.get("pageid"), "ns": namespace},
            )
            if candidate:
                candidates.append(candidate)
            if source.depth < max_category_depth:
                child_source = category_source_from_member(title, parent=source, namespace=namespace)
                if child_source:
                    discovered_sources.append(child_source)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        pages_seen += 1
        if not cmcontinue:
            break
    return candidates, discovered_sources


async def _discover_from_list(
    fetcher: WikiFetcher,
    source: DiscoverySource,
    *,
    known_region_names: set[str],
    stats: RegionDiscoveryStats,
) -> list[RegionCandidate]:
    result = await fetcher.fetch_wikitext(source.source_title)
    if not result.ok:
        raise RuntimeError(f"list fetch failed: HTTP {result.http_status}")
    data = result.json()
    wikitext = data.get("parse", {}).get("wikitext", "")
    candidates = extract_list_candidates(
        wikitext,
        source,
        known_region_names=known_region_names,
    )
    stats.list_links_seen += len(candidates)
    return candidates


async def _load_known_region_context_names(engine: object) -> set[str]:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT canonical_name, wikipedia_title
                        FROM wg_regions
                        WHERE wikipedia_title ILIKE 'Music of %'
                           OR wikipedia_title ILIKE 'Music in %'
                           OR (
                                kind in (
                                    'country',
                                    'territory',
                                    'city',
                                    'subregion',
                                    'continent',
                                    'cultural_region',
                                    'diaspora_region',
                                    'historical_region'
                                )
                                AND confidence >= 0.8
                           )
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
    names: set[str] = set()
    for row in rows:
        for value in (row["canonical_name"], row["wikipedia_title"]):
            if not value:
                continue
            clean = clean_region_name(value) or value
            names.add(clean.lower())
            title_region = region_name_from_music_title(value) or region_name_from_music_in_title(value)
            if title_region:
                names.add(title_region.lower())
    return names


async def _upsert_sources(conn: object, sources: list[DiscoverySource]) -> None:
    if not sources:
        return
    await conn.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO wg_region_discovery_sources (
                source_key,
                source_type,
                source_title,
                source_url,
                parent_key,
                depth,
                raw_payload
            )
            VALUES (
                :source_key,
                :source_type,
                :source_title,
                :source_url,
                :parent_key,
                :depth,
                jsonb_build_object('seeded_by', 'region_discovery')
            )
            ON CONFLICT (source_key) DO UPDATE
            SET source_url = excluded.source_url,
                parent_key = coalesce(wg_region_discovery_sources.parent_key, excluded.parent_key),
                depth = least(wg_region_discovery_sources.depth, excluded.depth)
        """),
        [
            {
                "source_key": source.source_key,
                "source_type": source.source_type,
                "source_title": source.source_title,
                "source_url": source.source_url,
                "parent_key": source.parent_key,
                "depth": source.depth,
            }
            for source in sources
        ],
    )


async def _upsert_candidates(conn: object, candidates: list[RegionCandidate]) -> None:
    await conn.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO wg_region_candidates (
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
                status,
                review_reason,
                raw_payload
            )
            VALUES (
                :candidate_key,
                :candidate_type,
                :title,
                :normalized_title,
                :suggested_region_id,
                :suggested_region_name,
                :source_key,
                :source_type,
                :source_title,
                :source_url,
                :source_section,
                :evidence_text,
                :confidence,
                :status,
                :review_reason,
                CAST(:raw_payload AS jsonb)
            )
            ON CONFLICT (candidate_key) DO UPDATE
            SET confidence = greatest(wg_region_candidates.confidence, excluded.confidence),
                status = CASE
                    WHEN wg_region_candidates.status = 'accepted' THEN wg_region_candidates.status
                    WHEN wg_region_candidates.status = 'rejected' THEN wg_region_candidates.status
                    ELSE excluded.status
                END,
                evidence_text = excluded.evidence_text,
                raw_payload = excluded.raw_payload,
                updated_at = now()
        """),
        [
            {
                "candidate_key": candidate.candidate_key,
                "candidate_type": candidate.candidate_type,
                "title": candidate.title,
                "normalized_title": candidate.normalized_title,
                "suggested_region_id": candidate.suggested_region_id,
                "suggested_region_name": candidate.suggested_region_name,
                "source_key": candidate.source.source_key,
                "source_type": candidate.source.source_type,
                "source_title": candidate.source.source_title,
                "source_url": candidate.source.source_url,
                "source_section": candidate.source_section,
                "evidence_text": candidate.evidence_text,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "review_reason": candidate.review_reason,
                "raw_payload": __import__("json").dumps(candidate.raw_payload),
            }
            for candidate in candidates
        ],
    )


async def _mark_source_status(
    source: DiscoverySource,
    status: str,
    *,
    conn: object | None = None,
) -> None:
    async def _execute(active_conn: object) -> None:
        await active_conn.execute(  # type: ignore[attr-defined]
            text("""
                UPDATE wg_region_discovery_sources
                SET status = :status,
                    last_fetched_at = now()
                WHERE source_key = :source_key
            """),
            {"status": status, "source_key": source.source_key},
        )

    if conn is not None:
        await _execute(conn)
        return
    engine = get_engine()
    async with engine.begin() as active_conn:
        await _execute(active_conn)
