"""Extract region-to-genre links directly from regional music pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import mwparserfromhell
import structlog
from sqlalchemy import text

from wiki_genres.crawler.fetcher import WikiFetcher
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.region_ownership import DEMONYM_OVERRIDES, classify_region_genre_ownership
from wiki_genres.loader.region_discovery import (
    DiscoverySource,
    SOURCE_LIST,
    extract_list_candidates,
)
from wiki_genres.loader.region_graph import relation_for_region_genre

logger = structlog.get_logger(__name__)

EXTRACTOR_MODEL = "deterministic-region-page-links-v4"
ARTICLE_SOURCE_TYPE = "wikipedia_article"
LIST_SOURCE_TYPE = "wikipedia_list"
NAVBOX_SOURCE_TYPE = "wikipedia_navbox"
SKIPPED_SECTION_TITLES = {
    "bibliography",
    "discography",
    "external links",
    "further reading",
    "notes",
    "references",
    "see also",
    "sources",
}
SKIPPED_SECTION_TERMS = {
    "artist",
    "artists",
    "band",
    "bands",
    "composer",
    "composers",
    "discography",
    "festival",
    "festivals",
    "musician",
    "musicians",
    "performer",
    "performers",
    "singer",
    "singers",
}
SKIPPED_NAMESPACES = {
    "category",
    "file",
    "help",
    "image",
    "portal",
    "special",
    "template",
    "wikipedia",
}
GENRE_SECTION_TERMS = {
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
}
GENRE_CONTEXT_TERMS = GENRE_SECTION_TERMS | {
    "forms",
    "music",
    "musical",
    "rhythm",
    "song",
    "songs",
}
LEAD_STRONG_TERMS = {
    "genre",
    "genres",
    "indigenous",
    "style",
    "styles",
    "tradition",
    "traditional",
}
NAVBOX_ALLOWED_CONTEXT_TERMS = {
    "1945",
    "1970",
    "1990",
    "classical music",
    "ethnic and regional",
    "ethnic music",
    "folk music",
    "folk song",
    "folk songs",
    "form",
    "forms",
    "genre",
    "genres",
    "light music",
    "main",
    "nationalistic",
    "patriotic",
    "post meiji",
    "post-war",
    "related music",
    "religious music",
    "semi-classical",
    "specific forms",
    "style",
    "styles",
    "traditional",
}
NAVBOX_SKIPPED_CONTEXT_TERMS = {
    "achievement",
    "achievements",
    "album chart",
    "albums chart",
    "anthem",
    "billboard",
    "chart",
    "charts",
    "instrument",
    "instruments",
    "karaoke chart",
    "media",
    "oricon",
    "regional and state",
    "singles chart",
    "timeline",
}
MUSIC_SIDEBAR_GENRE_PARAMS = {
    "genres": "Genres",
    "traditional": "Traditional music",
    "ethnic": "Ethnic music",
    "religious": "Religious music",
}
MUSIC_SIDEBAR_OPTIONAL_GENRE_PARAMS = {
    "otherforms": "Other forms",
}
SIDEBAR_SKIPPED_TITLE_TERMS = {
    "award",
    "awards",
    "chart",
    "charts",
    "festival",
    "festivals",
    "general topic",
    "general topics",
    "media",
    "regional and state",
    "timeline",
}
OWNER_TEMPLATE_ALIAS_TARGETS = {
    "andeanmusic": {"andes", "andean"},
    "balkan music": {"balkans", "balkan", "southeastern europe"},
    "celticmusic": {"celtic"},
    "hispanophone music": {"hispanophone"},
    "lusophonemusic": {"lusophone"},
    "middle eastern music": {"middle east", "middle eastern"},
    "nordic music": {"nordic", "nordic countries"},
    "usmusic": {"united states", "u.s.", "us"},
}


@dataclass(frozen=True)
class ExtractedRegionPageGenre:
    page_title: str
    section_title: str | None
    line_number: int | None
    evidence_kind: str
    link_title: str
    genre_id: str
    genre_title: str
    evidence_text: str
    confidence: float
    target_region_id: str | None = None
    target_region_name: str | None = None
    target_region_kind: str | None = None


@dataclass
class RegionPageGenreExtractionStats:
    pages_seen: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    pages_with_links: int = 0
    links_seen: int = 0
    proposals_upserted: int = 0
    sources_upserted: int = 0
    deleted_existing_relationships: int = 0
    deleted_existing_sources: int = 0
    dry_run: bool = False
    sample: list[str] = field(default_factory=list)
    failed_sample: list[str] = field(default_factory=list)


@dataclass
class RegionPageGenreCoverageStats:
    promoted_regions: int = 0
    regions_with_direct_genres: int = 0
    regions_without_direct_genres: int = 0
    regions_with_article_genres: int = 0
    article_edges: int = 0
    accepted_edges: int = 0
    pending_edges: int = 0
    rejected_edges: int = 0
    sample_without_direct_genres: list[str] = field(default_factory=list)


def normalize_link_title(title: str) -> str | None:
    """Normalize a wikitext link target into a Wikipedia article title."""
    clean = str(title).split("#", 1)[0].replace("_", " ").strip()
    if not clean:
        return None
    if ":" in clean:
        namespace = clean.split(":", 1)[0].strip().lower()
        if namespace in SKIPPED_NAMESPACES:
            return None
    return " ".join(clean.split())


def _normalize_lookup_title(title: str) -> str:
    return " ".join(title.replace("_", " ").strip().split()).casefold()


def _template_display_title(template_name: str) -> str:
    clean = " ".join(template_name.replace("_", " ").strip().split())
    if clean.casefold().startswith("template:"):
        return clean
    return f"Template:{clean}"


def _template_lookup_name(template_name: str) -> str:
    clean = _template_display_title(template_name)
    return clean.split(":", 1)[1] if ":" in clean else clean


def _compact_lookup_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_lookup_title(value or ""))


def _is_list_page_title(title: str | None) -> bool:
    return _normalize_lookup_title(title or "").startswith(("list of ", "lists of "))


def _is_region_list_source(
    *,
    page_title: str,
    region_name: str,
    region_kind: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> bool:
    normalized_title = _normalize_lookup_title(page_title)
    normalized_region = _normalize_lookup_title(region_name)
    if not _is_list_page_title(page_title):
        return False
    if not normalized_region or normalized_region not in normalized_title:
        return False
    if region_kind == "unknown" and normalized_region in genre_title_lookup:
        return False
    return True


def _is_regional_music_page_title(title: str | None) -> bool:
    normalized = _normalize_lookup_title(title or "")
    return normalized.startswith(
        (
            "music of ",
            "music in ",
            "traditional music of ",
        )
    )


def _region_navbox_template_titles(
    wikitext: str,
    *,
    page_title: str,
    region_name: str | None = None,
) -> list[str]:
    """Return directly transcluded regional music navboxes for this page."""
    owner_keys, owner_compact_keys = _region_navbox_owner_keys(
        page_title=page_title,
        region_name=region_name,
    )
    if not owner_keys and not owner_compact_keys:
        return []
    code = mwparserfromhell.parse(wikitext)
    titles: list[str] = []
    seen: set[str] = set()
    for template in code.filter_templates(recursive=False):
        template_title = _template_display_title(str(template.name))
        template_key = _normalize_lookup_title(_template_lookup_name(template_title))
        template_compact_key = _compact_lookup_key(template_key)
        if template_key not in owner_keys and template_compact_key not in owner_compact_keys:
            continue
        if template_title in seen:
            continue
        titles.append(template_title)
        seen.add(template_title)
    return titles


def _region_navbox_owner_keys(
    *,
    page_title: str,
    region_name: str | None = None,
) -> tuple[set[str], set[str]]:
    bases = {
        _normalize_lookup_title(region_name or ""),
        _normalize_lookup_title(_strip_region_music_prefix(page_title) or ""),
        _normalize_lookup_title(_strip_region_music_prefix(region_name) or ""),
    }
    bases = {base for base in bases if base}
    demonyms: set[str] = set()
    for base in list(bases):
        demonyms.update(DEMONYM_OVERRIDES.get(base, set()))
    terms = set(bases) | {_normalize_lookup_title(demonym) for demonym in demonyms}

    keys: set[str] = set()
    page_key = _normalize_lookup_title(page_title)
    if "music" in page_key or "folk" in page_key:
        keys.add(page_key)
    for term in terms:
        keys.update(
            {
                f"{term} folk music",
                f"{term} music",
                f"{term} traditional music",
                f"music in {term}",
                f"music of {term}",
                f"music of the {term}",
                f"traditional music of {term}",
            }
        )

    for alias_key, target_terms in OWNER_TEMPLATE_ALIAS_TARGETS.items():
        normalized_targets = {_normalize_lookup_title(target) for target in target_terms}
        if terms & normalized_targets or bases & normalized_targets:
            keys.add(_normalize_lookup_title(alias_key))

    return keys, {_compact_lookup_key(key) for key in keys}


def _is_bare_region_label(title: str, region_lookup: dict[str, tuple[str, str, str]]) -> bool:
    normalized = _normalize_lookup_title(title)
    if normalized not in region_lookup:
        return False
    return not _is_regional_music_page_title(title) and " music" not in normalized


def _section_title(section: Any) -> str | None:
    headings = section.filter_headings()
    if not headings:
        return None
    return " ".join(str(headings[-1].title).strip().split()) or None


def _is_skipped_section(section_title: str | None) -> bool:
    if not section_title:
        return False
    lower = section_title.strip().lower()
    if lower in SKIPPED_SECTION_TITLES:
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", lower) for term in SKIPPED_SECTION_TERMS)


def _section_confidence(section_title: str | None) -> float:
    if not section_title:
        return 0.76
    lower = section_title.lower()
    if any(term in lower for term in ("genre", "style", "tradition", "folk", "indigenous")):
        return 0.88
    if any(term in lower for term in ("popular", "classical", "regional", "local", "music")):
        return 0.82
    return 0.72


def _is_genre_bearing_section(section_title: str | None) -> bool:
    if not section_title:
        return False
    lower = section_title.lower()
    if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in SKIPPED_SECTION_TERMS):
        return False
    return any(re.search(rf"\b{re.escape(term)}\b", lower) for term in GENRE_SECTION_TERMS)


def _line_context_kind(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith(("{|", "|", "!", "|-", "||")):
        return "table_row"
    if stripped.startswith(";") and ":" in stripped:
        return "definition_row"
    if stripped.startswith(("*", "#")):
        return "list_row"
    return "prose"


def _line_has_genre_context(line: str) -> bool:
    lower = line.lower()
    return any(re.search(rf"\b{re.escape(term)}\b", lower) for term in GENRE_CONTEXT_TERMS)


def _line_has_strong_lead_context(line: str) -> bool:
    lower = line.lower()
    return any(re.search(rf"\b{re.escape(term)}\b", lower) for term in LEAD_STRONG_TERMS)


def _line_contains_link(line: str, link_title: str) -> bool:
    normalized = link_title.replace(" ", "_")
    escaped = re.escape(link_title)
    escaped_normalized = re.escape(normalized)
    return re.search(r"\[\[\s*(?:" + escaped + "|" + escaped_normalized + r")(?:[#|\]])", line, re.IGNORECASE) is not None


def _lines_for_link(section_text: str, link_title: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for index, line in enumerate(section_text.splitlines(), start=1):
        if _line_contains_link(line, link_title):
            matches.append((index, " ".join(line.strip().split())))
    return matches


def _evidence_kind_for_link(
    *,
    section_title: str | None,
    line: str | None,
    heading_match: bool = False,
) -> str | None:
    if heading_match:
        return "section_heading"
    if not line:
        return "genre_section_link" if _is_genre_bearing_section(section_title) else None

    line_kind = _line_context_kind(line)
    if _is_genre_bearing_section(section_title):
        if line_kind == "table_row":
            return "table_row_link"
        if line_kind == "definition_row":
            return "definition_row_link"
        if line_kind == "list_row":
            return "list_row_link"
        return "genre_section_link"

    if section_title is None:
        if _line_context_kind(line) in {"table_row", "definition_row", "list_row"} and _line_has_genre_context(line):
            return f"{line_kind}_link"
        if _line_has_strong_lead_context(line):
            return "lead_context_link"
        return None

    if line_kind in {"table_row", "definition_row", "list_row"} and _line_has_genre_context(line):
        return f"{line_kind}_link"
    return None


def _context_confidence(
    *,
    section_title: str | None,
    evidence_kind: str,
) -> float:
    base = _section_confidence(section_title)
    if evidence_kind == "section_heading":
        return max(base, 0.9)
    if evidence_kind in {"table_row_link", "definition_row_link"}:
        return max(base, 0.86)
    if evidence_kind == "list_row_link":
        return max(base, 0.84)
    if evidence_kind == "lead_context_link":
        return 0.74
    return base


def _append_match(
    extracted: list[ExtractedRegionPageGenre],
    seen: set[tuple[str, str | None, str]],
    *,
    page_title: str,
    section_title: str | None,
    line_number: int | None,
    evidence_kind: str,
    link_title: str,
    genre_id: str,
    genre_title: str,
    context_text: str | None = None,
    confidence: float,
    target_region_id: str | None = None,
    target_region_name: str | None = None,
    target_region_kind: str | None = None,
) -> None:
    if _normalize_lookup_title(genre_title) == _normalize_lookup_title(page_title):
        return
    key = (genre_id, section_title, evidence_kind)
    if key in seen:
        return
    seen.add(key)
    location = f"#{section_title}" if section_title else "lead"
    if line_number:
        location = f"{location}:L{line_number}"
    evidence_context = f" Context: {context_text}" if context_text else ""
    extracted.append(
        ExtractedRegionPageGenre(
            page_title=page_title,
            section_title=section_title,
            line_number=line_number,
            evidence_kind=evidence_kind,
            link_title=link_title,
            genre_id=genre_id,
            genre_title=genre_title,
            evidence_text=f"[[{link_title}]] linked from {page_title} {location}.{evidence_context}",
            confidence=confidence,
            target_region_id=target_region_id,
            target_region_name=target_region_name,
            target_region_kind=target_region_kind,
        )
    )


def _strip_template_markup(value: Any) -> str:
    return " ".join(mwparserfromhell.parse(str(value)).strip_code().split())


def _is_navbox_template(template: Any) -> bool:
    name = _normalize_lookup_title(str(template.name))
    return name in {"navbox", "template:navbox"}


def _is_music_sidebar_template(template: Any) -> bool:
    name = _normalize_lookup_title(str(template.name))
    return name in {"music of sidebar", "template:music of sidebar"}


def _is_collapsible_sidebar_template(template: Any) -> bool:
    name = _normalize_lookup_title(str(template.name))
    return name in {
        "sidebar",
        "template:sidebar",
        "sidebar with collapsible lists",
        "template:sidebar with collapsible lists",
    }


def _is_navbox_genre_context(context: list[str]) -> bool:
    text = " > ".join(item for item in context if item).casefold()
    if not text:
        return False
    if any(term in text for term in NAVBOX_SKIPPED_CONTEXT_TERMS):
        return False
    return any(term in text for term in NAVBOX_ALLOWED_CONTEXT_TERMS)


def _navbox_context_title(context: list[str]) -> str:
    return " > ".join(item for item in context if item) or "Navbox"


def _is_sidebar_genre_title(title: str) -> bool:
    text = _strip_template_markup(title).casefold()
    if not text:
        return False
    if any(term in text for term in SIDEBAR_SKIPPED_TITLE_TERMS):
        return False
    return any(term in text for term in NAVBOX_ALLOWED_CONTEXT_TERMS)


def _iter_navbox_link_titles(value: Any) -> list[tuple[str, str | None]]:
    """Return (link target, display text) from wikilinks and illm templates."""
    code = mwparserfromhell.parse(str(value))
    out: list[tuple[str, str | None]] = []
    for link in code.filter_wikilinks(recursive=True):
        link_title = normalize_link_title(str(link.title))
        if link_title:
            display = " ".join(str(link.text or link.title).strip().split()) or None
            out.append((link_title, display))

    for template in code.filter_templates(recursive=True):
        name = _normalize_lookup_title(str(template.name))
        if name not in {"illm", "interlanguage link multi"}:
            continue
        if not template.has(1):
            continue
        link_title = normalize_link_title(str(template.get(1).value))
        if not link_title:
            continue
        display = None
        if template.has("lt"):
            display = " ".join(str(template.get("lt").value).strip().split()) or None
        out.append((link_title, display))
    return out


def _is_navbox_link_skipped(link_title: str, display_text: str | None, genre_title: str) -> bool:
    labels = {
        _normalize_lookup_title(link_title),
        _normalize_lookup_title(display_text or ""),
        _normalize_lookup_title(genre_title),
    }
    return any("instrument" in label for label in labels if label)


def _append_navbox_links_from_value(
    value: Any,
    *,
    section_title: str,
    extracted: list[ExtractedRegionPageGenre],
    seen: set[tuple[str, str | None, str]],
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
    confidence: float = 0.9,
) -> None:
    for link_title, display_text in _iter_navbox_link_titles(value):
        match = genre_title_lookup.get(_normalize_lookup_title(link_title))
        if not match and display_text:
            match = genre_title_lookup.get(_normalize_lookup_title(display_text))
        if not match:
            continue
        genre_id, genre_title = match
        if _is_regional_music_page_title(genre_title):
            continue
        if _is_navbox_link_skipped(link_title, display_text, genre_title):
            continue
        _append_match(
            extracted,
            seen,
            page_title=page_title,
            section_title=section_title,
            line_number=None,
            evidence_kind="navbox_genre_link",
            link_title=link_title,
            genre_id=genre_id,
            genre_title=genre_title,
            context_text=section_title,
            confidence=confidence,
        )


def _extract_links_from_navbox_template(
    template: Any,
    *,
    context: list[str],
    extracted: list[ExtractedRegionPageGenre],
    seen: set[tuple[str, str | None, str]],
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> None:
    for index in range(1, 25):
        group_param = f"group{index}"
        list_param = f"list{index}"
        if not template.has(list_param):
            continue
        group_label = _strip_template_markup(template.get(group_param).value) if template.has(group_param) else ""
        next_context = [*context, group_label] if group_label else list(context)
        list_value = template.get(list_param).value

        for nested_template in mwparserfromhell.parse(str(list_value)).filter_templates(recursive=False):
            if _is_navbox_template(nested_template):
                _extract_links_from_navbox_template(
                    nested_template,
                    context=next_context,
                    extracted=extracted,
                    seen=seen,
                    page_title=page_title,
                    genre_title_lookup=genre_title_lookup,
                )

        if not _is_navbox_genre_context(next_context):
            continue

        section_title = _navbox_context_title(next_context)
        direct_list_code = mwparserfromhell.parse(str(list_value))
        for nested_template in list(direct_list_code.filter_templates(recursive=False)):
            if _is_navbox_template(nested_template):
                try:
                    direct_list_code.remove(nested_template)
                except ValueError:
                    continue
        _append_navbox_links_from_value(
            direct_list_code,
            section_title=section_title,
            extracted=extracted,
            seen=seen,
            page_title=page_title,
            genre_title_lookup=genre_title_lookup,
        )


def _extract_links_from_music_sidebar_template(
    template: Any,
    *,
    extracted: list[ExtractedRegionPageGenre],
    seen: set[tuple[str, str | None, str]],
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> None:
    for param_name, section_title in MUSIC_SIDEBAR_GENRE_PARAMS.items():
        if not template.has(param_name):
            continue
        _append_navbox_links_from_value(
            template.get(param_name).value,
            section_title=section_title,
            extracted=extracted,
            seen=seen,
            page_title=page_title,
            genre_title_lookup=genre_title_lookup,
        )

    for param_name, fallback_title in MUSIC_SIDEBAR_OPTIONAL_GENRE_PARAMS.items():
        if not template.has(param_name):
            continue
        label_name = f"{param_name}label"
        section_title = (
            _strip_template_markup(template.get(label_name).value)
            if template.has(label_name)
            else fallback_title
        )
        if not _is_sidebar_genre_title(section_title):
            continue
        _append_navbox_links_from_value(
            template.get(param_name).value,
            section_title=section_title,
            extracted=extracted,
            seen=seen,
            page_title=page_title,
            genre_title_lookup=genre_title_lookup,
            confidence=0.86,
        )


def _extract_links_from_collapsible_sidebar_template(
    template: Any,
    *,
    extracted: list[ExtractedRegionPageGenre],
    seen: set[tuple[str, str | None, str]],
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> None:
    for index in range(1, 40):
        list_param = f"list{index}"
        if not template.has(list_param):
            continue
        title = ""
        for title_param in (f"list{index}title", f"heading{index}", f"group{index}"):
            if template.has(title_param):
                title = _strip_template_markup(template.get(title_param).value)
                break
        if not _is_sidebar_genre_title(title):
            continue
        _append_navbox_links_from_value(
            template.get(list_param).value,
            section_title=title,
            extracted=extracted,
            seen=seen,
            page_title=page_title,
            genre_title_lookup=genre_title_lookup,
        )


def extract_region_navbox_genre_links(
    wikitext: str,
    *,
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> list[ExtractedRegionPageGenre]:
    """Return genre links from structured regional music navbox templates."""
    code = mwparserfromhell.parse(wikitext)
    extracted: list[ExtractedRegionPageGenre] = []
    seen: set[tuple[str, str | None, str]] = set()
    for template in code.filter_templates(recursive=False):
        if not _is_navbox_template(template):
            if _is_music_sidebar_template(template):
                _extract_links_from_music_sidebar_template(
                    template,
                    extracted=extracted,
                    seen=seen,
                    page_title=page_title,
                    genre_title_lookup=genre_title_lookup,
                )
            elif _is_collapsible_sidebar_template(template):
                _extract_links_from_collapsible_sidebar_template(
                    template,
                    extracted=extracted,
                    seen=seen,
                    page_title=page_title,
                    genre_title_lookup=genre_title_lookup,
                )
            continue
        _extract_links_from_navbox_template(
            template,
            context=[],
            extracted=extracted,
            seen=seen,
            page_title=page_title,
            genre_title_lookup=genre_title_lookup,
        )
    return extracted


def extract_region_page_genre_links(
    wikitext: str,
    *,
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
) -> list[ExtractedRegionPageGenre]:
    """Return exact approved-genre links from a regional music page body."""
    code = mwparserfromhell.parse(wikitext)
    for template in list(code.filter_templates(recursive=True)):
        try:
            code.remove(template)
        except ValueError:
            continue

    extracted: list[ExtractedRegionPageGenre] = []
    seen: set[tuple[str, str | None, str]] = set()

    for section in code.get_sections(flat=True, include_lead=True, include_headings=True):
        section_title = _section_title(section)
        if _is_skipped_section(section_title):
            continue
        confidence = _section_confidence(section_title)
        if section_title:
            heading_match = genre_title_lookup.get(_normalize_lookup_title(section_title))
            if heading_match:
                genre_id, genre_title = heading_match
                _append_match(
                    extracted,
                    seen,
                    page_title=page_title,
                    section_title=section_title,
                    line_number=None,
                    evidence_kind="section_heading",
                    link_title=section_title,
                    genre_id=genre_id,
                    genre_title=genre_title,
                    confidence=_context_confidence(
                        section_title=section_title,
                        evidence_kind="section_heading",
                    ),
                )
        for link in section.filter_wikilinks(recursive=True):
            link_title = normalize_link_title(str(link.title))
            if not link_title:
                continue
            lookup_key = _normalize_lookup_title(link_title)
            match = genre_title_lookup.get(lookup_key)
            if not match:
                continue
            genre_id, genre_title = match
            if _is_regional_music_page_title(genre_title):
                continue
            line_matches = _lines_for_link(str(section), link_title)
            if not line_matches:
                evidence_kind = _evidence_kind_for_link(
                    section_title=section_title,
                    line=None,
                )
                if not evidence_kind:
                    continue
                line_matches = [(0, "")]
            for line_number, line_text in line_matches:
                evidence_kind = _evidence_kind_for_link(
                    section_title=section_title,
                    line=line_text,
                )
                if not evidence_kind:
                    continue
                confidence = _context_confidence(
                    section_title=section_title,
                    evidence_kind=evidence_kind,
                )
                _append_match(
                    extracted,
                    seen,
                    page_title=page_title,
                    section_title=section_title,
                    line_number=line_number or None,
                    evidence_kind=evidence_kind,
                    link_title=link_title,
                    genre_id=genre_id,
                    genre_title=genre_title,
                    context_text=line_text or None,
                    confidence=confidence,
                )

    extracted.sort(key=lambda item: (item.genre_title.lower(), item.section_title or ""))
    return extracted


def extract_region_list_page_genre_links(
    wikitext: str,
    *,
    page_title: str,
    genre_title_lookup: dict[str, tuple[str, str]],
    region_lookup: dict[str, tuple[str, str, str]],
) -> list[ExtractedRegionPageGenre]:
    """Return list-derived genre links bound to the row/section region, not the list page."""
    known_region_names = {
        key
        for key in region_lookup
        if key and not key.startswith(("music of ", "music in ", "traditional music of "))
    }
    source = DiscoverySource(
        source_type=SOURCE_LIST,
        source_title=page_title,
        source_url="https://en.wikipedia.org/wiki/" + page_title.replace(" ", "_"),
    )
    candidates = extract_list_candidates(
        wikitext,
        source,
        known_region_names=known_region_names,
    )
    extracted: list[ExtractedRegionPageGenre] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        context_region = candidate.suggested_region_name or candidate.source_section
        if not context_region:
            continue
        target_region = region_lookup.get(_normalize_lookup_title(context_region))
        if not target_region:
            continue
        if candidate.candidate_type in {"music_region_page", "music_region_category"}:
            continue
        if _is_bare_region_label(candidate.title, region_lookup):
            continue
        genre_match = genre_title_lookup.get(_normalize_lookup_title(candidate.title))
        if not genre_match:
            continue
        genre_id, genre_title = genre_match
        key = (target_region[0], genre_id, candidate.source_section or "")
        if key in seen:
            continue
        seen.add(key)
        evidence_kind = str(candidate.raw_payload.get("list_row_type") or "list_row_link")
        line_number = candidate.raw_payload.get("list_line_number")
        extracted.append(
            ExtractedRegionPageGenre(
                page_title=page_title,
                section_title=candidate.source_section,
                line_number=int(line_number) if isinstance(line_number, int) else None,
                evidence_kind=evidence_kind,
                link_title=candidate.title,
                genre_id=genre_id,
                genre_title=genre_title,
                evidence_text=(
                    f"[[{candidate.title}]] listed under {context_region} "
                    f"in {page_title}."
                ),
                confidence=max(candidate.confidence, 0.72),
                target_region_id=target_region[0],
                target_region_name=target_region[1],
                target_region_kind=target_region[2],
            )
        )
    extracted.sort(
        key=lambda item: (
            item.target_region_name or "",
            item.genre_title.lower(),
            item.section_title or "",
        )
    )
    return extracted


async def _load_genre_lookup(conn: object) -> dict[str, tuple[str, str]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
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
    lookup = {
        _normalize_lookup_title(row["wikipedia_title"]): (row["id"], row["wikipedia_title"])
        for row in rows
    }

    redirect_rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT r.from_title, g.id, g.wikipedia_title
                    FROM wg_redirects r
                    JOIN wg_genres g ON g.id = r.to_genre_id
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    for row in redirect_rows:
        lookup.setdefault(
            _normalize_lookup_title(row["from_title"]),
            (row["id"], row["wikipedia_title"]),
        )
    return lookup


async def _load_region_lookup(conn: object) -> dict[str, tuple[str, str, str]]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT id, canonical_name, kind, display_title, wikipedia_title
                    FROM wg_regions
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    lookup: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        value = (row["id"], row["canonical_name"], row["kind"])
        for title in (
            row["canonical_name"],
            row["display_title"],
            row["wikipedia_title"],
            _strip_region_music_prefix(row["wikipedia_title"]),
        ):
            if title:
                lookup.setdefault(_normalize_lookup_title(title), value)
    return lookup


def _strip_region_music_prefix(title: str | None) -> str | None:
    normalized = " ".join((title or "").split())
    lowered = normalized.casefold()
    for prefix in ("music of the ", "music of ", "music in the ", "music in ", "traditional music of "):
        if lowered.startswith(prefix):
            return normalized[len(prefix) :]
    return None


async def extract_region_page_genres(
    *,
    dry_run: bool = False,
    reset_existing: bool = False,
    only_new: bool = False,
    from_cache: bool = False,
    limit: int | None = None,
    sample_size: int = 25,
) -> RegionPageGenreExtractionStats:
    """Fetch reviewed regional pages and stage exact linked genre children."""
    await apply_migrations()
    engine = get_engine()
    stats = RegionPageGenreExtractionStats(dry_run=dry_run)

    async with engine.connect() as conn:
        genre_lookup = await _load_genre_lookup(conn)
        region_lookup = await _load_region_lookup(conn)
        result = await conn.execute(
            text("""
                WITH page_sources AS (
                    SELECT
                        r.id AS region_id,
                        r.canonical_name,
                        r.kind,
                        r.wikipedia_title AS page_title,
                        0 AS source_rank
                    FROM wg_regions r
                    WHERE nullif(btrim(r.wikipedia_title), '') IS NOT NULL

                    UNION ALL

                    SELECT
                        page.region_id,
                        r.canonical_name,
                        r.kind,
                        g.wikipedia_title AS page_title,
                        1 AS source_rank
                    FROM wg_region_music_pages page
                    JOIN wg_regions r ON r.id = page.region_id
                    JOIN wg_genres g ON g.id = page.genre_id
                    WHERE nullif(btrim(g.wikipedia_title), '') IS NOT NULL

                    UNION ALL

                    SELECT
                        p.region_id,
                        r.canonical_name,
                        r.kind,
                        g.wikipedia_title AS page_title,
                        2 AS source_rank
                    FROM wg_region_promoted_genres p
                    JOIN wg_regions r ON r.id = p.region_id
                    JOIN wg_genres g ON g.id = p.genre_id
                    WHERE nullif(btrim(g.wikipedia_title), '') IS NOT NULL
                ),
                deduped AS (
                    SELECT DISTINCT ON (region_id, lower(page_title))
                        region_id,
                        canonical_name,
                        kind,
                        page_title,
                        source_rank
                    FROM page_sources
                    ORDER BY region_id, lower(page_title), source_rank
                )
                SELECT
                    d.region_id,
                    d.canonical_name,
                    d.kind,
                    d.page_title
                FROM deduped d
                LEFT JOIN LATERAL (
                    SELECT count(*) AS accepted_genres
                    FROM wg_region_genre_relationships rel
                    WHERE rel.region_id = d.region_id
                      AND rel.status = 'accepted'
                ) rel_counts ON true
                ORDER BY
                    coalesce(rel_counts.accepted_genres, 0),
                    d.canonical_name,
                    d.source_rank,
                    d.page_title
                LIMIT coalesce(:limit_value, 2147483647)
            """),
            {"limit_value": limit},
        )
        region_rows = result.mappings().fetchall()

    stats.pages_seen = len(region_rows)
    fetcher = WikiFetcher(from_cache=from_cache)
    try:
        page_results: list[tuple[dict[str, Any], list[ExtractedRegionPageGenre]]] = []
        for row in region_rows:
            row_dict = dict(row)
            page_title = row_dict["page_title"]
            fetch_result = await fetcher.fetch_wikitext(page_title)
            if not fetch_result.ok:
                stats.pages_failed += 1
                if len(stats.failed_sample) < sample_size:
                    stats.failed_sample.append(f"{page_title} HTTP {fetch_result.http_status}")
                continue
            stats.pages_fetched += 1
            data = fetch_result.json()
            wikitext = data.get("parse", {}).get("wikitext", "")
            if _is_list_page_title(page_title):
                if _is_region_list_source(
                    page_title=page_title,
                    region_name=row_dict["canonical_name"],
                    region_kind=row_dict["kind"],
                    genre_title_lookup=genre_lookup,
                ):
                    links = extract_region_list_page_genre_links(
                        wikitext,
                        page_title=page_title,
                        genre_title_lookup=genre_lookup,
                        region_lookup=region_lookup,
                    )
                else:
                    links = []
            else:
                links = extract_region_page_genre_links(
                    wikitext,
                    page_title=page_title,
                    genre_title_lookup=genre_lookup,
                )
                for template_title in _region_navbox_template_titles(
                    wikitext,
                    page_title=page_title,
                    region_name=row_dict["canonical_name"],
                ):
                    template_fetch = await fetcher.fetch_wikitext(template_title)
                    if not template_fetch.ok:
                        continue
                    template_wikitext = template_fetch.json().get("parse", {}).get("wikitext", "")
                    links.extend(
                        extract_region_navbox_genre_links(
                            template_wikitext,
                            page_title=template_title,
                            genre_title_lookup=genre_lookup,
                        )
                    )
            if links:
                stats.pages_with_links += 1
                stats.links_seen += len(links)
                page_results.append((row_dict, links))
                for link in links:
                    if len(stats.sample) < sample_size:
                        section = link.section_title or "lead"
                        stats.sample.append(f"{page_title}#{section} -> {link.genre_title}")
    finally:
        await fetcher.aclose()

    if dry_run:
        return stats

    async with engine.begin() as conn:
        if reset_existing:
            if only_new:
                raise ValueError("only_new cannot be combined with reset_existing")
            deleted_relationships = await conn.execute(
                text("""
            DELETE FROM wg_region_genre_relationships
                    WHERE source_type IN (:article_source_type, :list_source_type, :navbox_source_type)
                      AND raw_payload ->> 'extractor_model' LIKE 'deterministic-region-page-links-v%'
                """),
                {
                    "article_source_type": ARTICLE_SOURCE_TYPE,
                    "list_source_type": LIST_SOURCE_TYPE,
                    "navbox_source_type": NAVBOX_SOURCE_TYPE,
                },
            )
            stats.deleted_existing_relationships = int(deleted_relationships.rowcount or 0)
            deleted_sources = await conn.execute(
                text("""
                    DELETE FROM wg_region_sources
                    WHERE source_type IN (:article_source_type, :list_source_type, :navbox_source_type)
                      AND extractor_model LIKE 'deterministic-region-page-links-v%'
                """),
                {
                    "article_source_type": ARTICLE_SOURCE_TYPE,
                    "list_source_type": LIST_SOURCE_TYPE,
                    "navbox_source_type": NAVBOX_SOURCE_TYPE,
                },
            )
            stats.deleted_existing_sources = int(deleted_sources.rowcount or 0)

        for row, links in page_results:
            source_url = "https://en.wikipedia.org/wiki/" + row["page_title"].replace(" ", "_")
            for link in links:
                target_region_id = link.target_region_id or row["region_id"]
                target_region_name = link.target_region_name or row["canonical_name"]
                target_region_kind = link.target_region_kind or row["kind"]
                source_page_title = link.page_title or row["page_title"]
                source_url = "https://en.wikipedia.org/wiki/" + source_page_title.replace(" ", "_")
                if link.evidence_kind == "navbox_genre_link":
                    source_type = NAVBOX_SOURCE_TYPE
                elif _is_list_page_title(row["page_title"]):
                    source_type = LIST_SOURCE_TYPE
                else:
                    source_type = ARTICLE_SOURCE_TYPE
                source_conflict_sql = (
                    "DO NOTHING"
                    if only_new
                    else """
                        DO UPDATE
                        SET evidence_text = excluded.evidence_text,
                            extractor_model = excluded.extractor_model,
                            confidence = greatest(wg_region_sources.confidence, excluded.confidence),
                            raw_payload = wg_region_sources.raw_payload || excluded.raw_payload
                    """
                )
                source_result = await conn.execute(
                    text(f"""
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
                        {source_conflict_sql}
                    """),
                    {
                        "region_id": target_region_id,
                        "source_type": source_type,
                        "source_url": source_url,
                        "source_title": source_page_title,
                        "source_section": link.section_title,
                        "evidence_text": f"Genre links extracted from {source_page_title}.",
                        "extractor_model": EXTRACTOR_MODEL,
                        "confidence": link.confidence,
                        "raw_payload": json.dumps(
                            {
                                "extractor_model": EXTRACTOR_MODEL,
                                "source_region_id": row["region_id"],
                                "source_region_name": row["canonical_name"],
                                "target_region_id": target_region_id,
                                "target_region_name": target_region_name,
                            }
                        ),
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
                        "region_id": target_region_id,
                        "source_type": source_type,
                        "source_url": source_url,
                        "source_title": source_page_title,
                        "source_section": link.section_title,
                    },
                )
                stats.sources_upserted += int(source_result.rowcount or 0)
                relation = relation_for_region_genre(
                    {
                        "candidate_type": "regional_genre_page",
                        "title": link.genre_title,
                        "source_title": source_page_title,
                        "source_section": link.section_title,
                    },
                    target_region_kind,
                )
                ownership_decision = classify_region_genre_ownership(
                    {
                        "relation": relation,
                        "source_type": source_type,
                        "source_title": source_page_title,
                        "source_section": link.section_title,
                        "evidence_kind": link.evidence_kind,
                        "evidence_text": link.evidence_text,
                        "region_name": target_region_name,
                        "region_wikipedia_title": row["page_title"],
                        "genre_title": link.genre_title,
                    }
                )
                relation = ownership_decision.relation or relation
                relationship_conflict_sql = (
                    "DO NOTHING"
                    if only_new
                    else """
                        DO UPDATE
                        SET source_id = excluded.source_id,
                            evidence_text = excluded.evidence_text,
                            confidence = greatest(
                                wg_region_genre_relationships.confidence,
                                excluded.confidence
                            ),
                            raw_payload = wg_region_genre_relationships.raw_payload
                                || excluded.raw_payload,
                            updated_at = now()
                    """
                )
                relationship_result = await conn.execute(
                    text(f"""
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
                        {relationship_conflict_sql}
                    """),
                    {
                        "region_id": target_region_id,
                        "genre_id": link.genre_id,
                        "relation": relation,
                        "source_id": source_id,
                        "source_type": source_type,
                        "source_url": source_url,
                        "source_title": source_page_title,
                        "source_section": link.section_title,
                        "evidence_text": link.evidence_text,
                        "confidence": link.confidence,
                        "raw_payload": json.dumps(
                            {
                                "extractor_model": EXTRACTOR_MODEL,
                                "link_title": link.link_title,
                                "canonical_genre_title": link.genre_title,
                                "evidence_kind": link.evidence_kind,
                                "line_number": link.line_number,
                                "source_region_id": row["region_id"],
                                "source_region_name": row["canonical_name"],
                                "target_region_id": target_region_id,
                                "target_region_name": target_region_name,
                                "ownership_review": {
                                    "ownership_class": ownership_decision.ownership_class,
                                    "relation": relation,
                                    "reason": ownership_decision.reason,
                                    "reviewer_model": "deterministic-region-ownership-v1",
                                },
                            }
                        ),
                    },
                )
                stats.proposals_upserted += int(relationship_result.rowcount or 0)

    logger.info(
        "region_page_genre_extraction_complete",
        pages_seen=stats.pages_seen,
        pages_fetched=stats.pages_fetched,
        pages_failed=stats.pages_failed,
        proposals_upserted=stats.proposals_upserted,
        dry_run=dry_run,
    )
    return stats


async def audit_region_page_genre_coverage(
    *,
    sample_size: int = 25,
) -> RegionPageGenreCoverageStats:
    """Summarize direct regional child-genre coverage after page extraction."""
    await apply_migrations()
    engine = get_engine()
    stats = RegionPageGenreCoverageStats()

    async with engine.connect() as conn:
        summary = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            count(*) AS promoted_regions,
                            count(*) FILTER (
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM wg_region_genre_relationships rel
                                    WHERE rel.region_id = p.region_id
                                      AND rel.status = 'accepted'
                                )
                            ) AS regions_with_direct_genres,
                            count(*) FILTER (
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM wg_region_genre_relationships rel
                                    WHERE rel.region_id = p.region_id
                                      AND rel.status = 'accepted'
                                      AND rel.source_type = 'wikipedia_article'
                                )
                            ) AS regions_with_article_genres
                        FROM wg_region_promoted_genres p
                    """)
                )
            )
            .mappings()
            .one()
        )
        stats.promoted_regions = int(summary["promoted_regions"] or 0)
        stats.regions_with_direct_genres = int(summary["regions_with_direct_genres"] or 0)
        stats.regions_without_direct_genres = (
            stats.promoted_regions - stats.regions_with_direct_genres
        )
        stats.regions_with_article_genres = int(summary["regions_with_article_genres"] or 0)

        rel_summary = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            count(*) FILTER (WHERE status = 'accepted') AS accepted_edges,
                            count(*) FILTER (
                                WHERE status = 'accepted'
                                  AND source_type = 'wikipedia_article'
                            ) AS article_edges,
                            count(*) FILTER (WHERE status in ('proposed', 'needs_review')) AS pending_edges,
                            count(*) FILTER (WHERE status = 'rejected') AS rejected_edges
                        FROM wg_region_genre_relationships
                    """)
                )
            )
            .mappings()
            .one()
        )
        stats.accepted_edges = int(rel_summary["accepted_edges"] or 0)
        stats.article_edges = int(rel_summary["article_edges"] or 0)
        stats.pending_edges = int(rel_summary["pending_edges"] or 0)
        stats.rejected_edges = int(rel_summary["rejected_edges"] or 0)

        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            r.canonical_name,
                            g.wikipedia_title
                        FROM wg_region_promoted_genres p
                        JOIN wg_regions r ON r.id = p.region_id
                        JOIN wg_genres g ON g.id = p.genre_id
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM wg_region_genre_relationships rel
                            WHERE rel.region_id = p.region_id
                              AND rel.status = 'accepted'
                        )
                        ORDER BY coalesce(g.monthly_views_p30, 0) DESC,
                                 r.canonical_name
                        LIMIT :sample_size
                    """),
                    {"sample_size": sample_size},
                )
            )
            .mappings()
            .fetchall()
        )
        stats.sample_without_direct_genres = [
            f"{row['canonical_name']} ({row['wikipedia_title']})" for row in rows
        ]

    return stats
