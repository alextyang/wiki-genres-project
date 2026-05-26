"""Pydantic response models for the wiki-genres REST API (v1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    evidence_relation: str | None = None
    to_monthly_views_p30: int | None = None
    to_similarity_color: str | None = None
    to_color_confidence: float | None = None


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


class ReachableParentOut(BaseModel):
    genre_id: str
    genre_monthly_views_p30: int | None = None
    genre_year_start: int | None = None
    parent_genre_id: str
    parent_title: str
    parent_monthly_views_p30: int | None = None
    parent_year_start: int | None = None
    root_genre_id: str
    root_title: str
    root_monthly_views_p30: int | None = None
    parent_relation: str
    parent_stored_relation: str | None = None
    parent_evidence_relation: str | None = None
    parent_source: str
    parent_ordinal: int
    parent_depth_from_music: int
    depth_from_music: int
    path_genre_ids: list[str]
    path_titles: list[str]


class RegionVariantOut(BaseModel):
    region_key: str
    region_name: str
    region_id: str | None = None
    region_kind: str | None = None
    x: float | None = None
    y: float | None = None
    genre_id: str | None = None
    base_genre_id: str | None = None
    candidate_id: int | None = None
    wikipedia_title: str
    display_title: str | None = None
    monthly_views_p30: int | None = None
    similarity_color: str | None = None
    color_confidence: float | None = None
    match_type: str


class RegionVariantsResult(BaseModel):
    genre_id: str | None
    wikipedia_title: str
    items: list[RegionVariantOut]


class MapRegionItemOut(BaseModel):
    region_id: str | None = None
    region_key: str
    region_name: str
    region_kind: str | None = None
    map_key: str
    feature_key: str
    feature_name: str
    genre_id: str | None = None
    base_genre_id: str | None = None
    candidate_id: int | None = None
    wikipedia_title: str | None = None
    display_title: str
    monthly_views_p30: int | None = None
    similarity_color: str | None = None
    color_confidence: float | None = None
    match_type: str
    selectable: bool = True
    role: str = "region"
    selectable_for: str | None = None
    matched_region_id: str | None = None
    matched_region_name: str | None = None
    matched_region_kind: str | None = None
    matched_genre_id: str | None = None
    mount_parent_region_id: str | None = None
    mount_parent_region_name: str | None = None
    list_group_region_id: str | None = None
    list_group_region_name: str | None = None
    list_group_region_kind: str | None = None
    selection_priority: int | None = None
    icon_feature_keys: list[str] = Field(default_factory=list)
    represented_genre_ids: list[str] = Field(default_factory=list)
    represented_titles: list[str] = Field(default_factory=list)
    represented_children: list[dict] = Field(default_factory=list)


class MapContextOut(BaseModel):
    genre_id: str | None
    wikipedia_title: str
    active_map: str
    map_label: str | None = None
    selected_region: MapRegionItemOut | None = None
    selectable_regions: list[MapRegionItemOut] = []
    context_highlights: list[MapRegionItemOut] = []
    parent_regions: list[MapRegionItemOut] = []


class GenrePlaylistTrackOut(BaseModel):
    genre_id: str
    ordinal: int
    song_title: str
    artist: str
    youtube_url: str


class GenrePlaylistResult(BaseModel):
    genre_id: str
    wikipedia_title: str
    tracks: list[GenrePlaylistTrackOut]


class FeedbackPayload(BaseModel):
    report_type: str = Field(max_length=80)
    genre_name: str | None = Field(default=None, max_length=220)
    genre_id: str | None = Field(default=None, max_length=80)
    relationship: str | None = Field(default=None, max_length=320)
    youtube_url: str | None = Field(default=None, max_length=600)
    youtube_title: str | None = Field(default=None, max_length=260)
    youtube_artist: str | None = Field(default=None, max_length=220)
    page_url: str | None = Field(default=None, max_length=900)
    graph_path: str | None = Field(default=None, max_length=900)
    notes: str | None = Field(default=None, max_length=4000)


class FeedbackResult(BaseModel):
    ok: bool


class YoutubePlaybackErrorPayload(BaseModel):
    genre_id: str = Field(max_length=80)
    youtube_url: str = Field(max_length=600)
    youtube_title: str | None = Field(default=None, max_length=260)
    youtube_artist: str | None = Field(default=None, max_length=220)
    error: str | None = Field(default=None, max_length=120)
    page_url: str | None = Field(default=None, max_length=900)


class TimelineYearHintOut(BaseModel):
    year_start: int
    year_end: int | None = None
    estimated_start: int | None = None
    estimated_end: int | None = None
    year_mean: float | None = None
    year_sd: float | None = None
    year_observation_count: int | None = None
    beginning_start: int | None = None
    beginning_end: int | None = None
    beginning_mean: float | None = None
    beginning_sd: float | None = None
    beginning_observation_count: int | None = None
    relevance_start: int | None = None
    relevance_end: int | None = None
    relevance_mean: float | None = None
    relevance_sd: float | None = None
    relevance_observation_count: int | None = None
    confidence: str
    year_kind: str
    source_type: str
    source_field: str
    evidence: str
    reason: str
    score: int


class TimelineNodeOut(BaseModel):
    id: str
    wikipedia_title: str
    label: str
    depth: int
    lane: int
    x: float
    y: float
    year_start: int | None = None
    year_end: int | None = None
    year_confidence: str | None = None
    year_kind: str | None = None
    is_inferred_year: bool = False
    monthly_views_p30: int | None = None
    similarity_color: str | None = None
    semantic_root: str | None = None
    timeline_rank: float = 1
    timeline_importance: float = 0
    selected_distance: int | None = None
    selected_direction: str | None = None
    selected_connection_count: int | None = None
    selected_focus_score: float | None = None
    hint: TimelineYearHintOut | None = None


class TimelineEdgeOut(BaseModel):
    from_genre_id: str
    to_genre_id: str
    relation: str
    source: str
    route: list[list[float]]


class TimelineResult(BaseModel):
    root_id: str
    scope: str
    min_confidence: str
    year_min: int | None = None
    year_max: int | None = None
    nodes: list[TimelineNodeOut]
    edges: list[TimelineEdgeOut]
    stats: dict[str, int]


class GenreCloudNodeOut(BaseModel):
    id: str
    wikipedia_title: str
    label: str
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    box_width: float | None = None
    box_height: float | None = None
    depth_from_music: int | None = None
    semantic_root_id: str | None = None
    semantic_root_title: str | None = None
    monthly_views_p30: int | None = None
    similarity_color: str | None = None
    color_confidence: float | None = None
    has_playlist: bool = False
    child_connection_count: int = 0
    parent_connection_count: int = 0
    priority: float = 0
    lod_score: float = 0
    radial_x: float | None = None
    radial_y: float | None = None
    radial_compaction_version: str | None = None
    min_visible_scale: float = 2.0
    show_scale: float = 2.0
    hide_scale: float = 1.85
    lod_rank: int = 0
    lod_tier: int = 5


class GenreCloudResult(BaseModel):
    nodes: list[GenreCloudNodeOut]
    stats: dict


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
    monthly_views_p30: int | None = None
    similarity_color: str | None = None
    color_confidence: float | None = None


class GenreDetail(GenreListItem):
    """Full genre payload — all edges, aliases, origins, instruments, categories."""

    outbound_edges: list[EdgeOut] = []
    inbound_edges: list[EdgeOut] = []
    aliases: list[AliasOut] = []
    origins: list[OriginOut] = []
    instruments: list[str] = []
    categories: list[str] = []
    youtube_items: list[GenrePlaylistTrackOut] = []
    youtube_urls: list[str] = []


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

    matched_by: str  # "title" | "alias" | "redirect" | "qid"
    input: str
    genre: GenreDetail


class SearchHit(BaseModel):
    id: str
    wikipedia_title: str
    wikipedia_url: str | None
    wikidata_qid: str | None
    has_infobox: bool
    summary: str | None
    rank: float


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]
    total: int


class TraversableSearchHit(SearchHit):
    monthly_views_p30: int | None = None
    depth_from_music: int
    path_genre_ids: list[str]
    path_titles: list[str]


class TraversableSearchResults(BaseModel):
    query: str
    hits: list[TraversableSearchHit]
    total: int


# ------------------------------------------------------------------ #
# Diff                                                                #
# ------------------------------------------------------------------ #


class DiffGenreEntry(BaseModel):
    id: str
    wikipedia_title: str
    wikipedia_url: str | None
    wikidata_qid: str | None
    change_type: str  # "added" | "updated" | "edges_changed"
    last_changed_at: datetime | None


class DiffResult(BaseModel):
    since: datetime
    as_of: datetime
    genres_changed: list[DiffGenreEntry]
    total: int


# ------------------------------------------------------------------ #
# Stats                                                               #
# ------------------------------------------------------------------ #


class PageviewEntry(BaseModel):
    year: int
    month: int
    views: int


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
