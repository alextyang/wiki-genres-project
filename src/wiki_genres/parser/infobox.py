"""Infobox parser for ``{{Infobox music genre}}`` wikitext templates.

Uses ``mwparserfromhell`` to walk the template AST.  Each parameter value is
handled uniformly: wikilinks are extracted in document order, then residual
plaintext is split and cleaned.

Handles the common encoding variants:
- ``[[Target|Display]]`` wikilinks
- ``{{hlist|A|B|C}}``, ``{{flatlist|...}}``, ``{{ublist|...}}``,
  ``{{plainlist|...}}``
- ``<br>``-separated values
- Comma, semicolon, and ``•`` delimiters in free text
- ``[[File:...]]`` / ``[[Image:...]]`` — skipped
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import mwparserfromhell
import structlog

from wiki_genres.parser.types import (
    InternalLink,
    ParsedEdge,
    ParsedGenre,
    ParsedOrigin,
)

logger = structlog.get_logger(__name__)

# Maps infobox parameter names → edge relation.
_EDGE_FIELDS: dict[str, str] = {
    "stylistic_origins": "stylistic_origin",
    "stylistic_origins_2": "stylistic_origin",
    "stylistic_origin": "stylistic_origin",
    "cultural_origins": "cultural_origin",
    "cultural_origin": "cultural_origin",
    "derivatives": "derivative",
    "derivative": "derivative",
    "subgenres": "subgenre",
    "subgenre": "subgenre",
    "fusion_genres": "fusion_genre",
    "fusion_genre": "fusion_genre",
    "regional_scenes": "regional_scene",
    "regional_scene": "regional_scene",
    "local_scenes": "local_scene",
    "local_scene": "local_scene",
}

_ALIAS_FIELDS = {"other_names", "other_name", "also_known_as", "also known as", "aka"}
_INSTRUMENT_FIELDS = {"instruments", "instrument", "instruments_2"}
_COLOR_FIELDS = {"color_background", "color", "bgcolor", "colour_background"}
_ORIGIN_TEMPORAL_FIELDS = {"origin", "cultural_origins", "cultural_origin"}

_SKIP_LINK_PREFIXES = {
    "File:", "Image:", "Media:", "Category:", "Wikipedia:", "WP:",
    "Help:", "Template:", "Portal:",
}

WIKIPEDIA_BASE = "https://en.wikipedia.org/wiki/"


def parse_genre_page(
    wikitext: str,
    title: str,
    summary: str | None = None,
    wikidata_qid: str | None = None,
    upstream_revision: int | None = None,
    categories: list[str] | None = None,
) -> ParsedGenre:
    """Parse a Wikipedia article's wikitext and return a ``ParsedGenre``."""
    sha256 = hashlib.sha256(wikitext.encode()).hexdigest()
    wikipedia_url = WIKIPEDIA_BASE + title.replace(" ", "_")

    wikicode = mwparserfromhell.parse(wikitext)
    infobox = _find_infobox(wikicode)

    if infobox is None:
        return ParsedGenre(
            wikipedia_title=title,
            wikipedia_url=wikipedia_url,
            wikidata_qid=wikidata_qid,
            has_infobox=False,
            summary=summary,
            infobox_color=None,
            upstream_revision=upstream_revision,
            raw_wikitext_sha256=sha256,
            categories=categories or [],
        )

    edges: list[ParsedEdge] = []
    aliases: list[str] = []
    origins: list[ParsedOrigin] = []
    instruments: list[str] = []
    infobox_color: str | None = None
    new_titles: set[str] = set()

    for param in infobox.params:
        param_name = param.name.strip().lower().replace(" ", "_")
        param_value = str(param.value)

        # ----- Typed edge fields ----------------------------------------
        if param_name in _EDGE_FIELDS:
            relation = _EDGE_FIELDS[param_name]
            items = _extract_items(param_value)
            for ordinal, item in enumerate(items):
                raw_label = item.display if isinstance(item, InternalLink) else item
                wiki_target = (
                    _normalise_title(item.target) if isinstance(item, InternalLink) else None
                )
                edges.append(
                    ParsedEdge(
                        relation=relation,
                        raw_label=raw_label,
                        wiki_target=wiki_target,
                        source="infobox",
                        ordinal=ordinal,
                    )
                )
                if wiki_target and not _skip_link(wiki_target):
                    new_titles.add(wiki_target)  # already normalised above

            # Cultural/temporal origin fields also feed wg_origins (prose capture).
            if relation == "cultural_origin":
                raw = _strip_wikicode(param_value).strip()
                if raw:
                    origins.append(_parse_origin_string(raw))

        # ----- Aliases / synonyms ----------------------------------------
        elif param_name in _ALIAS_FIELDS:
            for item in _extract_items(param_value):
                text_val = item.display if isinstance(item, InternalLink) else item
                cleaned = _clean_alias(text_val)
                if cleaned:
                    aliases.append(cleaned)

        # ----- Instruments -----------------------------------------------
        elif param_name in _INSTRUMENT_FIELDS:
            for item in _extract_items(param_value):
                label = item.display if isinstance(item, InternalLink) else item
                label = label.strip()
                if label:
                    instruments.append(label)

        # ----- Color -------------------------------------------------------
        elif param_name in _COLOR_FIELDS and infobox_color is None:
            infobox_color = _extract_color(param_value)

        # ----- Temporal / cultural origins (prose) -------------------------
        elif param_name in _ORIGIN_TEMPORAL_FIELDS:
            # cultural_origins also generates edges (handled above); here we
            # capture the raw text for wg_origins when it's free-form prose.
            raw = _strip_wikicode(param_value).strip()
            if raw:
                parsed = _parse_origin_string(raw)
                origins.append(parsed)

    return ParsedGenre(
        wikipedia_title=title,
        wikipedia_url=wikipedia_url,
        wikidata_qid=wikidata_qid,
        has_infobox=True,
        summary=summary,
        infobox_color=infobox_color,
        upstream_revision=upstream_revision,
        raw_wikitext_sha256=sha256,
        infobox_edges=edges,
        aliases=list(dict.fromkeys(aliases)),  # dedupe preserving order
        origins=origins,
        instruments=instruments,
        categories=categories or [],
        new_genre_titles=sorted(new_titles),
    )


# ------------------------------------------------------------------ #
# Wikicode extraction helpers                                          #
# ------------------------------------------------------------------ #

def _find_infobox(wikicode: Any) -> Any | None:
    """Return the first ``Infobox music genre`` template, or None."""
    for template in wikicode.filter_templates():
        name = template.name.strip().lower()
        if "infobox music genre" in name:
            return template
    return None


def _extract_items(param_value: str) -> list[InternalLink | str]:
    """Extract a list of items from a wikitext parameter value.

    Returns a mixed list: ``InternalLink`` where the item was a wikilink,
    plain ``str`` otherwise.  Preserves document order.
    """
    wc = mwparserfromhell.parse(param_value)
    items: list[InternalLink | str] = []
    seen_targets: set[str] = set()

    # First pass: extract wikilinks in order.
    for node in wc.nodes:
        if isinstance(node, mwparserfromhell.nodes.Wikilink):
            target = str(node.title).strip()
            if _skip_link(target):
                continue
            display = str(node.text).strip() if node.text else target
            # Strip trailing disambiguation.
            display = _clean_display(display)
            if target not in seen_targets:
                items.append(InternalLink(target=target, display=display))
                seen_targets.add(target)

    # Second pass: expand list-style templates (hlist, flatlist, etc.) and
    # collect any free-text that wasn't captured via wikilinks.
    for template in wc.filter_templates():
        tname = template.name.strip().lower()
        if tname in {"hlist", "flatlist", "ublist", "plainlist", "ubl", "bulleted list"}:
            for tparam in template.params:
                if not tparam.name.strip().isdigit() and tparam.name.strip() not in {
                    "class", "style", "indent", "ul_style", "li_style"
                }:
                    continue
                raw = str(tparam.value).strip()
                sub_links = _extract_items(raw)
                for sub in sub_links:
                    if isinstance(sub, InternalLink) and sub.target not in seen_targets:
                        items.append(sub)
                        seen_targets.add(sub.target)
                    elif isinstance(sub, str) and sub not in {
                        i.display if isinstance(i, InternalLink) else i for i in items
                    }:
                        items.append(sub)

    # Third pass: if the parameter had no wikilinks at all, split free text.
    if not any(isinstance(i, InternalLink) for i in items):
        plain = _strip_wikicode(param_value)
        items = _split_free_text(plain)

    return [i for i in items if _item_is_meaningful(i)]


def _strip_wikicode(text: str) -> str:
    """Return plain text with all markup stripped."""
    try:
        return mwparserfromhell.parse(text).strip_code().strip()
    except Exception:  # noqa: BLE001
        return text.strip()


def _split_free_text(text: str) -> list[str]:
    """Split comma/semicolon/br/bullet-separated free text into items."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*[*#:;]+\s*", "", text, flags=re.MULTILINE)
    parts = re.split(r"[,;\n•/]", text)
    return [p.strip() for p in parts if p.strip()]


def _clean_display(display: str) -> str:
    """Remove disambiguation suffixes like ' (music genre)' from display text."""
    return re.sub(r"\s*\([^)]+\)\s*$", "", display).strip()


def _clean_alias(text: str) -> str:
    """Normalise an alias string."""
    text = re.sub(r"\s*\([^)]*\)", "", text).strip()
    return text.strip(" .,;")


def _skip_link(target: str) -> bool:
    """Return True for links that should not become edges or frontier items."""
    for prefix in _SKIP_LINK_PREFIXES:
        if target.startswith(prefix) or target.startswith(prefix.lower()):
            return True
    return False


def _normalise_title(target: str) -> str:
    """Convert a wikilink target to a canonical Wikipedia title."""
    # Capitalise first character; replace underscores with spaces.
    title = target.replace("_", " ")
    return title[:1].upper() + title[1:] if title else title


def _item_is_meaningful(item: InternalLink | str) -> bool:
    label = item.display if isinstance(item, InternalLink) else item
    return bool(label and len(label.strip()) > 1)


# ------------------------------------------------------------------ #
# Color extraction                                                     #
# ------------------------------------------------------------------ #

_HEX_RE = re.compile(r"#?([0-9A-Fa-f]{6})")


def _extract_color(raw: str) -> str | None:
    """Return a #RRGGBB color string if one can be extracted, else None."""
    plain = _strip_wikicode(raw)
    m = _HEX_RE.search(plain)
    return f"#{m.group(1).upper()}" if m else None


# ------------------------------------------------------------------ #
# Origin parsing                                                       #
# ------------------------------------------------------------------ #

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})s?\b")
_YEAR_RANGE_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})[-–](1[0-9]{3}|20[0-9]{2})\b")
_REGION_HINTS = re.compile(
    r"\b(United States|United Kingdom|United Arab Emirates|"
    r"U\.S\.|U\.K\.|USA|UK|"
    r"Jamaica|Nigeria|Brazil|Germany|France|Japan|South Korea|Korea|"
    r"Northern California|Southern California|"
    r"Chicago|New York(?:\s+City)?|Los Angeles|Detroit|"
    r"London|Berlin|Paris|Manchester|"
    r"South Bronx|Bronx|Compton|Atlanta|Houston|Toronto|Miami|"
    r"New Orleans|Nashville|Philadelphia|Seattle|Baltimore|"
    r"Inland Empire|Bay Area)\b",
    re.IGNORECASE,
)


def _parse_origin_string(raw: str) -> ParsedOrigin:
    """Best-effort parse of a temporal/cultural origin string."""
    kind = "temporal" if _YEAR_RE.search(raw) else "cultural"
    year_start: int | None = None
    year_end: int | None = None
    region: str | None = None

    range_m = _YEAR_RANGE_RE.search(raw)
    if range_m:
        year_start = int(range_m.group(1))
        year_end = int(range_m.group(2))
    else:
        m = _YEAR_RE.search(raw)
        if m:
            year_str = m.group(0).rstrip("s")
            year_start = int(year_str)

    region_m = _REGION_HINTS.search(raw)
    if region_m:
        region = region_m.group(0)

    return ParsedOrigin(
        kind=kind,
        value=raw,
        parsed_year_start=year_start,
        parsed_year_end=year_end,
        parsed_region=region,
    )
