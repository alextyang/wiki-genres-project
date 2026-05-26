"""Domain types shared between the parser and loader layers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InternalLink:
    """A ``[[Target|Display]]`` wikilink extracted from an infobox field.

    ``target`` is the raw link target (may include underscores and disambiguation
    suffixes like ``_(music_genre)``).  ``display`` is the visible text; equals
    ``target`` when no pipe is present.
    """

    target: str
    display: str


@dataclass
class ParsedEdge:
    """One edge extracted from the infobox or Wikidata."""

    relation: str  # vocabulary defined in wg_edges check constraint
    raw_label: str  # verbatim label as it appears in the source
    wiki_target: str | None  # link target (Wikipedia title), if known
    source: str  # 'infobox' | 'wikidata'
    ordinal: int = 0


@dataclass
class ParsedOrigin:
    kind: str  # 'cultural' | 'temporal'
    value: str  # raw string, e.g. "Late 1970s, New York City"
    parsed_year_start: int | None = None
    parsed_year_end: int | None = None
    parsed_region: str | None = None


@dataclass
class ParsedGenre:
    """Everything the parser extracted for one genre page.

    Produced by ``infobox.parse_genre_page()``.  Consumed by the loader.
    """

    wikipedia_title: str
    wikipedia_url: str
    wikidata_qid: str | None
    has_infobox: bool
    summary: str | None
    infobox_color: str | None
    upstream_revision: int | None
    raw_wikitext_sha256: str | None

    # Typed edges from the infobox (source='infobox').
    infobox_edges: list[ParsedEdge] = field(default_factory=list)

    # Typed edges from Wikidata (source='wikidata').  Populated later.
    wikidata_edges: list[ParsedEdge] = field(default_factory=list)

    # Synonyms / other names.
    aliases: list[str] = field(default_factory=list)

    # Origin context.
    origins: list[ParsedOrigin] = field(default_factory=list)

    # Instruments (raw labels; may be wikilinks).
    instruments: list[str] = field(default_factory=list)

    # Wikipedia categories.
    categories: list[str] = field(default_factory=list)

    # Wikipedia titles discovered in the infobox that should be enqueued.
    new_genre_titles: list[str] = field(default_factory=list)


@dataclass
class ParsedWikidataEntity:
    """Subset of a Wikidata entity relevant to the genre graph."""

    qid: str
    aliases: list[str] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)
