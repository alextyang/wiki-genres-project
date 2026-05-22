"""Pydantic response models for the wiki-genres REST API (v1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ------------------------------------------------------------------ #
# Shared primitives                                                    #
# ------------------------------------------------------------------ #

class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_genre_id: str
    to_genre_id: str | None
    to_raw_label: str
    relation: str
    source: str
    ordinal: int


class AliasOut(BaseModel):
    alias: str
    source: str


class OriginOut(BaseModel):
    kind: str
    value: str
    parsed_year_start: int | None
    parsed_year_end: int | None
    parsed_region: str | None


class NeighborOut(BaseModel):
    id: str
    wikipedia_title: str
    wikidata_qid: str | None
    has_infobox: bool
    infobox_color: str | None
    relation: str
    source: str
    depth: int


# ------------------------------------------------------------------ #
# Genre representations                                               #
# ------------------------------------------------------------------ #

class GenreListItem(BaseModel):
    id: str
    wikidata_qid: str | None
    wikipedia_title: str
    wikipedia_url: str | None
    has_infobox: bool
    infobox_color: str | None
    summary: str | None
    last_changed_at: datetime | None
    last_fetched_at: datetime | None


class GenreDetail(GenreListItem):
    """Full genre payload — all edges, aliases, origins, instruments, categories."""

    outbound_edges: list[EdgeOut] = []
    inbound_edges: list[EdgeOut] = []
    aliases: list[AliasOut] = []
    origins: list[OriginOut] = []
    instruments: list[str] = []
    categories: list[str] = []


# ------------------------------------------------------------------ #
# List / pagination wrappers                                          #
# ------------------------------------------------------------------ #

class PaginatedGenres(BaseModel):
    items: list[GenreListItem]
    total: int
    page: int
    size: int
    pages: int


# ------------------------------------------------------------------ #
# Resolve / search                                                    #
# ------------------------------------------------------------------ #

class ResolveResult(BaseModel):
    """Canonical genre for an alias, title, or QID lookup."""

    matched_by: str   # "title" | "alias" | "redirect" | "qid"
    input: str
    genre: GenreDetail


class SearchHit(BaseModel):
    id: str
    wikipedia_title: str
    wikidata_qid: str | None
    has_infobox: bool
    summary: str | None
    rank: float


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]
    total: int


# ------------------------------------------------------------------ #
# Diff                                                                #
# ------------------------------------------------------------------ #

class DiffGenreEntry(BaseModel):
    id: str
    wikipedia_title: str
    wikidata_qid: str | None
    change_type: str   # "added" | "updated" | "edges_changed"
    last_changed_at: datetime | None


class DiffResult(BaseModel):
    since: datetime
    as_of: datetime
    genres_changed: list[DiffGenreEntry]
    total: int


# ------------------------------------------------------------------ #
# Stats                                                               #
# ------------------------------------------------------------------ #

class StatsResult(BaseModel):
    version: str
    genres: int | None
    genres_with_infobox: int | None
    edges: int | None
    edges_resolved: int | None
    aliases: int | None
    last_snapshot_id: str | None
    last_snapshot_finished: datetime | None
    last_sync_started_at: datetime | None
    last_sync_finished_at: datetime | None
    frontier_depth: int | None
