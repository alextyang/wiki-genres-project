"""Materialize a purpose-built semantic layout for the cloud view.

This layout intentionally does not consume ``wg_genre_colors``. Colors remain a
separate visual encoding; placement is driven by a local text/metadata vector,
active graph relationships, playlist examples, and Music-root reachability.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.cloud_text_metrics import measure_cloud_label
from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.cloud_display_cache import refresh_cloud_display_cache
from wiki_genres.loader.cycle_guard import DEFAULT_ROOT_TITLES

logger = structlog.get_logger(__name__)

LAYOUT_VERSION = "semantic-cloud-stable-lod-v1"
VECTOR_VERSION = "weighted-local-tfidf-v1"
EDGE_VERSION = "semantic-graph-playlist-v1"
GENERAL_LAYOUT_KEY = "general_music_v1"
MUSIC_ROOT_ID = "__music_root__"
MUSIC_REGION_TITLE_RE = re.compile(r"\bmusic\s+(?:of|in)\b", re.IGNORECASE)
FONT_SIZE = 13.0
BROAD_ROOT_TITLE_ORDER = (
    (
        "Rock music",
        "Heavy metal music",
        "Experimental music",
        "Electronic music",
        "Pop music",
        "Hip-hop",
        "Hip hop music",
        "Rhythm and blues",
        "Blues",
        "Jazz",
        "Classical music",
        "Soundtrack",
        "Religious music",
        "Folk music",
        "Country music",
        "World music",
        "Latin music",
        "Reggae",
    )
    + tuple(
        title
        for title in DEFAULT_ROOT_TITLES
        if title
        not in {
            "Rock music",
            "Heavy metal music",
            "Experimental music",
            "Electronic music",
            "Pop music",
            "Hip-hop",
            "Hip hop music",
            "Rhythm and blues",
            "Blues",
            "Jazz",
            "Classical music",
            "Soundtrack",
            "Religious music",
            "Folk music",
            "Country music",
            "World music",
            "Latin music",
            "Reggae",
        }
    )
    + (
        "Ancient music",
        "Early music",
        "Medieval music",
        "Renaissance music",
        "Baroque music",
    )
)

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
REGIONAL_TITLE_RE = re.compile(r"\bmusic\s+(?:of|in)\b", re.IGNORECASE)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "category",
    "citation",
    "dead",
    "external",
    "failed",
    "for",
    "from",
    "genre",
    "genres",
    "in",
    "is",
    "it",
    "links",
    "music",
    "musical",
    "of",
    "on",
    "or",
    "pages",
    "project",
    "sister",
    "style",
    "styles",
    "that",
    "the",
    "to",
    "using",
    "verification",
    "weasel",
    "worded",
    "with",
}

MAINTENANCE_TEXT_RE = re.compile(
    r"\b("
    r"articles?|pages?|wikipedia|wikidata|commons|category|cs1|short description|"
    r"dead external|citation|verification|cleanup|maintenance|"
    r"webarchive|wayback|use dmy|use mdy|all stub|stub articles?|"
    r"articles with|pages with|sister project|commons category|"
    r"weasel|peacock|unreferenced|sources|identifiers"
    r")\b",
    re.IGNORECASE,
)

RELATION_WEIGHT = {
    "subgenre": 1.0,
    "derivative": 0.82,
    "fusion_genre": 0.76,
    "regional_scene": 0.24,
}

SOURCE_WEIGHT = {
    "manual_curation": 1.15,
    "infobox": 1.0,
    "wikidata": 0.9,
    "inbound_index": 0.72,
    "region_promotion": 0.78,
}


@dataclass
class SemanticGenre:
    genre_id: str
    title: str
    summary: str | None
    monthly_views_p30: int | None
    depth_from_music: int
    root_genre_id: str
    root_title: str
    child_connection_count: int
    parent_connection_count: int
    has_playlist: bool
    path_genre_ids: tuple[str, ...] = ()
    aliases: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    playlist_terms: list[str] = field(default_factory=list)
    terms: Counter[str] = field(default_factory=Counter)
    vector: dict[str, float] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    lod_score: float = 0.0
    min_visible_scale: float = 2.0
    show_scale: float = 2.0
    hide_scale: float = 1.85
    lod_rank: int = 0
    lod_tier: int = 5

    @property
    def label(self) -> str:
        return _display_title(self.title)

    @property
    def priority(self) -> float:
        return (
            float(self.child_connection_count) * 1_000_000_000
            + float(self.monthly_views_p30 or 0)
            + float(self.parent_connection_count) / 1_000_000
        )

    @property
    def width(self) -> float:
        return self.text_width

    @property
    def height(self) -> float:
        return self.text_height

    @property
    def text_width(self) -> float:
        return measure_cloud_label(self.label).text_width

    @property
    def text_height(self) -> float:
        return measure_cloud_label(self.label).text_height

    @property
    def box_width(self) -> float:
        return measure_cloud_label(self.label).box_width

    @property
    def box_height(self) -> float:
        return measure_cloud_label(self.label).box_height

    @property
    def box_pad_x(self) -> float:
        return measure_cloud_label(self.label).box_pad_x

    @property
    def box_pad_y(self) -> float:
        return measure_cloud_label(self.label).box_pad_y


@dataclass(frozen=True)
class SemanticEdge:
    from_genre_id: str
    to_genre_id: str
    weight: float
    sources: dict[str, float]


@dataclass
class SemanticCloudLayoutStats:
    layout_key: str
    total_genres: int = 0
    vector_rows: int = 0
    semantic_edges: int = 0
    graph_edges: int = 0
    materialized_edges: int = 0
    layout_rows: int = 0
    deleted_vectors: int = 0
    deleted_edges: int = 0
    deleted_layouts: int = 0
    dry_run: bool = False
    sample: list[dict] = field(default_factory=list)
    quality_metrics: dict[str, float | int] = field(default_factory=dict)
    quality_sample: list[dict] = field(default_factory=list)


def layout_key_for_region(region_id: str) -> str:
    return f"country:{region_id}:v1"


def layout_key_for_root(root_genre_id: str | None, *, region_id: str | None = None) -> str:
    if region_id:
        return layout_key_for_region(region_id)
    return f"region:{root_genre_id}:v1" if root_genre_id else GENERAL_LAYOUT_KEY


def _display_title(title: str | None) -> str:
    label = (title or "").replace("_", " ").strip()
    label = re.sub(r"\s+\((music|genre|music genre)\)$", "", label, flags=re.I)
    label = re.sub(r"\s+music$", "", label, flags=re.I)
    return label or (title or "")


def _stable_unit(value: str) -> float:
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value / 4294967295


def _tokens(text_value: str | None) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall((text_value or "").lower()):
        if len(token) < 2 or token in STOPWORDS or token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _add_terms(terms: Counter[str], text_value: str | None, weight: float) -> None:
    raw_tokens = _tokens(text_value)
    for token in raw_tokens:
        terms[token] += weight
    for left, right in zip(raw_tokens, raw_tokens[1:], strict=False):
        if left not in STOPWORDS and right not in STOPWORDS:
            terms[f"{left}_{right}"] += weight * 0.85


def _build_terms(genre: SemanticGenre) -> tuple[Counter[str], str]:
    terms: Counter[str] = Counter()
    pieces: list[str] = [genre.title]

    _add_terms(terms, genre.title, 7.0)
    _add_terms(terms, genre.label, 5.0)
    if genre.summary:
        pieces.append(genre.summary)
        _add_terms(terms, genre.summary, 0.7)
    _add_terms(terms, genre.root_title, 2.5)

    for alias in genre.aliases[:8]:
        pieces.append(alias)
        _add_terms(terms, alias, 3.2)
    useful_categories = [
        category
        for category in genre.categories
        if category and not MAINTENANCE_TEXT_RE.search(category)
    ]
    for category in useful_categories[:16]:
        pieces.append(category)
        _add_terms(terms, category, 1.8)
    for origin in genre.origins[:10]:
        pieces.append(origin)
        _add_terms(terms, origin, 2.3)
    for instrument in genre.instruments[:10]:
        pieces.append(instrument)
        _add_terms(terms, instrument, 2.1)
    for playlist_item in genre.playlist_terms[:16]:
        pieces.append(playlist_item)
        _add_terms(terms, playlist_item, 1.4)

    return terms, " | ".join(piece for piece in pieces if piece)


def _build_vectors(genres: list[SemanticGenre], *, max_terms: int = 80) -> dict[str, str]:
    documents: dict[str, str] = {}
    document_frequency: Counter[str] = Counter()
    for genre in genres:
        terms, document = _build_terms(genre)
        genre.terms = terms
        documents[genre.genre_id] = document
        document_frequency.update(terms.keys())

    total = max(1, len(genres))
    max_df = max(24, min(420, int(total * 0.32)))
    for genre in genres:
        weighted: dict[str, float] = {}
        for term, term_weight in genre.terms.items():
            df = document_frequency[term]
            if df > max_df:
                continue
            idf = math.log((1 + total) / (1 + df)) + 1.0
            weighted[term] = float(term_weight) * idf

        top_items = sorted(weighted.items(), key=lambda item: (-item[1], item[0]))[:max_terms]
        norm = math.sqrt(sum(value * value for _, value in top_items)) or 1.0
        genre.vector = {term: round(value / norm, 6) for term, value in top_items}
    return documents


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _semantic_edges(
    genres: list[SemanticGenre],
    *,
    neighbors_per_node: int = 14,
) -> list[SemanticEdge]:
    by_id = {genre.genre_id: genre for genre in genres}
    postings: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for genre in genres:
        for term, value in genre.vector.items():
            postings[term].append((genre.genre_id, value))

    pair_scores: dict[tuple[str, str], float] = defaultdict(float)
    max_postings = max(12, min(260, int(len(genres) * 0.08)))
    for items in postings.values():
        if len(items) < 2 or len(items) > max_postings:
            continue
        items = sorted(items)
        for index, (left_id, left_value) in enumerate(items):
            for right_id, right_value in items[index + 1 :]:
                pair_scores[(left_id, right_id)] += left_value * right_value

    neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left_id, right_id), score in pair_scores.items():
        if score < 0.075:
            continue
        left = by_id[left_id]
        right = by_id[right_id]
        same_root_bonus = 0.035 if left.root_genre_id == right.root_genre_id else 0.0
        depth_delta = abs(left.depth_from_music - right.depth_from_music)
        adjusted = score + same_root_bonus - min(0.05, depth_delta * 0.008)
        if adjusted < 0.075:
            continue
        neighbors[left_id].append((right_id, adjusted))
        neighbors[right_id].append((left_id, adjusted))

    accepted: set[tuple[str, str]] = set()
    edges: list[SemanticEdge] = []
    for genre_id, items in neighbors.items():
        for other_id, score in sorted(items, key=lambda item: (-item[1], item[0]))[
            :neighbors_per_node
        ]:
            key = tuple(sorted((genre_id, other_id)))
            if key in accepted:
                continue
            accepted.add(key)
            edges.append(
                SemanticEdge(
                    from_genre_id=key[0],
                    to_genre_id=key[1],
                    weight=max(0.05, min(1.0, score)),
                    sources={"semantic_vector": round(score, 4)},
                )
            )
    return edges


def _graph_edges(raw_edges: list[dict], genre_ids: set[str]) -> list[SemanticEdge]:
    weighted: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in raw_edges:
        left_id = row["from_genre_id"]
        right_id = row["to_genre_id"]
        if left_id not in genre_ids or right_id not in genre_ids or left_id == right_id:
            continue
        relation = row["relation"]
        if relation == "related_genre" and row.get("evidence_relation") in RELATION_WEIGHT:
            relation = row["evidence_relation"]
        relation_weight = RELATION_WEIGHT.get(relation, 0.0)
        if relation_weight <= 0:
            continue
        source_weight = SOURCE_WEIGHT.get(row["source"], 0.82)
        key = tuple(sorted((left_id, right_id)))
        weighted[key][f"graph:{relation}"] += relation_weight * source_weight

    edges: list[SemanticEdge] = []
    for (left_id, right_id), sources in weighted.items():
        total = sum(sources.values())
        edges.append(
            SemanticEdge(
                from_genre_id=left_id,
                to_genre_id=right_id,
                weight=max(0.08, min(1.35, total)),
                sources={source: round(value, 4) for source, value in sorted(sources.items())},
            )
        )
    return edges


def _merge_edges(edges: list[SemanticEdge]) -> list[SemanticEdge]:
    merged: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for edge in edges:
        key = tuple(sorted((edge.from_genre_id, edge.to_genre_id)))
        for source, value in edge.sources.items():
            merged[key][source] += value

    rows: list[SemanticEdge] = []
    for (left_id, right_id), sources in merged.items():
        total = sum(sources.values())
        rows.append(
            SemanticEdge(
                from_genre_id=left_id,
                to_genre_id=right_id,
                weight=max(0.05, min(1.8, total)),
                sources={source: round(value, 4) for source, value in sorted(sources.items())},
            )
        )
    rows.sort(key=lambda edge: (-edge.weight, edge.from_genre_id, edge.to_genre_id))
    return rows


def _project_vector(vector: dict[str, float], salt: str = "") -> tuple[float, float]:
    x = 0.0
    y = 0.0
    total = 0.0
    for term, value in vector.items():
        angle = _stable_unit(f"{salt}:{term}:angle") * math.tau
        x += math.cos(angle) * value
        y += math.sin(angle) * value
        total += abs(value)
    if total <= 0:
        return (0.0, 0.0)
    return (x / total, y / total)


def _root_order(genres: list[SemanticGenre]) -> list[str]:
    roots: dict[str, dict[str, float]] = {}
    root_titles: dict[str, str] = {}
    root_weight: Counter[str] = Counter()
    for genre in genres:
        root_titles[genre.root_genre_id] = genre.root_title
        root_weight[genre.root_genre_id] += max(
            1.0,
            math.log10((genre.monthly_views_p30 or 0) + 10),
        )
        root_vector = roots.setdefault(genre.root_genre_id, {})
        for term, value in genre.vector.items():
            root_vector[term] = root_vector.get(term, 0.0) + value

    if not roots:
        return []
    remaining = set(roots)
    current = max(remaining, key=lambda root_id: (root_weight[root_id], root_titles[root_id]))
    ordered = [current]
    remaining.remove(current)
    while remaining:
        current_vector = roots[current]
        current = max(
            remaining,
            key=lambda root_id: (
                _cosine(current_vector, roots[root_id]),
                root_weight[root_id],
                root_titles[root_id],
            ),
        )
        ordered.append(current)
        remaining.remove(current)
    return ordered


def _path_parent_id(genre: SemanticGenre) -> str | None:
    if len(genre.path_genre_ids) < 2:
        return None
    return genre.path_genre_ids[-2]


def _root_geometry(
    genres: list[SemanticGenre],
    *,
    center_genre_id: str | None,
) -> dict[str, tuple[float, float, float]]:
    root_ids = _root_order(genres)
    broad_title_index = {title: index for index, title in enumerate(BROAD_ROOT_TITLE_ORDER)}
    broad_root_ids = {
        genre.root_genre_id: broad_title_index[genre.root_title]
        for genre in genres
        if genre.root_title in broad_title_index
    }
    root_vectors: dict[str, dict[str, float]] = defaultdict(dict)
    for genre in genres:
        vector = root_vectors[genre.root_genre_id]
        for term, value in genre.vector.items():
            vector[term] = vector.get(term, 0.0) + value

    geometry: dict[str, tuple[float, float, float]] = {}
    for root_id in root_ids:
        if center_genre_id:
            angle = _stable_unit(f"{root_id}:scoped-root") * math.tau
            geometry[root_id] = (angle, 0.0, 0.0)
            continue

        if root_id in broad_root_ids:
            angle = (
                -math.pi / 2
                + (broad_root_ids[root_id] / max(1, len(BROAD_ROOT_TITLE_ORDER))) * math.tau
            )
            radius = 1320.0
        else:
            vx, vy = _project_vector(root_vectors.get(root_id, {}), salt=f"{root_id}:root")
            angle = math.atan2(vy, vx) if vx or vy else _stable_unit(root_id) * math.tau
            radius = 1700.0

        geometry[root_id] = (angle, math.cos(angle) * radius, math.sin(angle) * radius * 0.72)
    return geometry


def _initial_positions(
    genres: list[SemanticGenre],
    *,
    center_genre_id: str | None,
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    root_geometry = _root_geometry(genres, center_genre_id=center_genre_id)
    by_depth = sorted(
        genres,
        key=lambda genre: (genre.depth_from_music, genre.root_title.lower(), genre.title.lower()),
    )
    for genre in by_depth:
        if center_genre_id and genre.genre_id == center_genre_id:
            positions[genre.genre_id] = (0.0, 0.0)
            continue

        root_angle, root_x, root_y = root_geometry.get(
            genre.root_genre_id,
            (_stable_unit(genre.root_genre_id) * math.tau, 0.0, 0.0),
        )
        if genre.depth_from_music <= 1 and not center_genre_id:
            positions[genre.genre_id] = (root_x, root_y)
            continue

        vx, vy = _project_vector(genre.vector, salt=genre.root_genre_id)
        parent_id = _path_parent_id(genre)
        parent_x, parent_y = positions.get(parent_id or "", (root_x, root_y))
        parent_angle = math.atan2(parent_y - root_y, parent_x - root_x) if parent_id else root_angle
        local_angle = (
            parent_angle * 0.72
            + root_angle * 0.28
            + (_stable_unit(f"{genre.genre_id}:angle") - 0.5) * 0.62
            + math.atan2(vy, vx) * 0.12
        )
        parent_distance = (
            66.0
            + min(7, max(1, genre.depth_from_music)) * 18.0
            + (_stable_unit(f"{genre.genre_id}:radius") - 0.5) * 26.0
        )
        parent_target = (
            parent_x + math.cos(local_angle) * parent_distance,
            parent_y + math.sin(local_angle) * parent_distance * 0.82,
        )
        territory_radius = 105.0 + max(0, genre.depth_from_music - 1) * 62.0
        territory_target = (
            root_x + math.cos(root_angle) * territory_radius + vx * 65.0,
            root_y + math.sin(root_angle) * territory_radius * 0.72 + vy * 45.0,
        )
        parent_mix = 0.9 if parent_id else 0.58
        positions[genre.genre_id] = (
            parent_target[0] * parent_mix + territory_target[0] * (1 - parent_mix),
            parent_target[1] * parent_mix + territory_target[1] * (1 - parent_mix),
        )
    return positions


def _edge_layout_weight(edge: SemanticEdge, by_id: dict[str, SemanticGenre]) -> float:
    left = by_id.get(edge.from_genre_id)
    right = by_id.get(edge.to_genre_id)
    if left is None or right is None:
        return 0.0

    graph_subgenre = edge.sources.get("graph:subgenre", 0.0)
    graph_derivative = edge.sources.get("graph:derivative", 0.0)
    graph_fusion = edge.sources.get("graph:fusion_genre", 0.0)
    graph_regional = edge.sources.get("graph:regional_scene", 0.0)
    semantic = edge.sources.get("semantic_vector", 0.0)

    graph_weight = graph_subgenre * 2.8 + graph_derivative * 1.45 + graph_fusion * 1.25
    graph_weight += graph_regional * 0.42
    semantic_weight = semantic * (0.58 if left.root_genre_id == right.root_genre_id else 0.18)
    if graph_weight <= 0 and left.root_genre_id != right.root_genre_id:
        semantic_weight *= 0.35
    return max(0.0, min(5.0, graph_weight + semantic_weight))


def _edge_desired_distance(edge: SemanticEdge, by_id: dict[str, SemanticGenre]) -> float:
    left = by_id[edge.from_genre_id]
    right = by_id[edge.to_genre_id]
    depth_delta = abs(left.depth_from_music - right.depth_from_music)
    if edge.sources.get("graph:subgenre", 0.0) > 0:
        return 92.0 + min(5, depth_delta) * 16.0
    if edge.sources.get("graph:derivative", 0.0) > 0:
        return 150.0 + min(5, depth_delta) * 18.0
    if edge.sources.get("graph:regional_scene", 0.0) > 0:
        return 132.0 + min(5, depth_delta) * 18.0
    if left.root_genre_id == right.root_genre_id:
        return 185.0 + min(6, depth_delta) * 20.0
    return 320.0


def _pack_labels(genres: list[SemanticGenre], *, iterations: int = 38) -> None:
    if len(genres) < 2:
        return
    ordered = sorted(genres, key=lambda genre: (-genre.priority, genre.title.lower()))
    for _ in range(iterations):
        moved = False
        grid: dict[tuple[int, int], list[SemanticGenre]] = defaultdict(list)
        cell_size = 86.0
        for genre in ordered:
            key = (math.floor(genre.x / cell_size), math.floor(genre.y / cell_size))
            candidates: list[SemanticGenre] = []
            for gx in range(key[0] - 1, key[0] + 2):
                for gy in range(key[1] - 1, key[1] + 2):
                    candidates.extend(grid.get((gx, gy), ()))

            for other in candidates:
                min_x = (genre.box_width + other.box_width) / 2
                min_y = (genre.box_height + other.box_height) / 2
                dx = genre.x - other.x
                dy = genre.y - other.y
                if abs(dx) >= min_x or abs(dy) >= min_y:
                    continue
                push_x = math.copysign((min_x - abs(dx)) * 0.62, dx or 1.0)
                push_y = math.copysign((min_y - abs(dy)) * 0.62, dy or 1.0)
                if abs(push_x) < abs(push_y) * 1.7:
                    genre.x += push_x
                else:
                    genre.y += push_y
                moved = True

            key = (math.floor(genre.x / cell_size), math.floor(genre.y / cell_size))
            grid[key].append(genre)
        if not moved:
            return


def _assign_lod(genres: list[SemanticGenre], *, center_genre_id: str | None) -> None:
    if not genres:
        return
    max_children = max(1, *(genre.child_connection_count for genre in genres))
    max_views = max(1.0, *(math.log1p(genre.monthly_views_p30 or 0) for genre in genres))
    max_parents = max(1, *(genre.parent_connection_count for genre in genres))
    for genre in genres:
        child_score = genre.child_connection_count / max_children
        view_score = math.log1p(genre.monthly_views_p30 or 0) / max_views
        parent_score = genre.parent_connection_count / max_parents
        word_penalty = max(0, len(TOKEN_RE.findall(genre.label)) - 3) * 0.045
        regional_penalty = 0.28 if REGIONAL_TITLE_RE.search(genre.label) else 0.0
        center_boost = 0.2 if center_genre_id and genre.genre_id == center_genre_id else 0.0
        if genre.depth_from_music <= 1:
            depth_boost = 0.08
        elif genre.depth_from_music <= 2:
            depth_boost = 0.035
        else:
            depth_boost = 0.0
        playlist_boost = 0.025 if genre.has_playlist else 0.0
        genre.lod_score = round(
            max(
                0.0,
                min(
                    1.0,
                    child_score * 0.52
                    + view_score * 0.31
                    + parent_score * 0.12
                    + center_boost
                    + depth_boost
                    + playlist_boost
                    - word_penalty
                    - regional_penalty,
                ),
            ),
            6,
        )

    ordered = sorted(
        genres,
        key=lambda genre: (
            -genre.lod_score,
            -genre.child_connection_count,
            -(genre.monthly_views_p30 or 0),
            -genre.parent_connection_count,
            genre.title.lower(),
        ),
    )
    total = max(1, len(ordered) - 1)
    for rank, genre in enumerate(ordered):
        normalized = rank / total
        scale = 0.35 + (normalized**0.72) * 1.65
        if genre.depth_from_music <= 1 or genre.genre_id == center_genre_id:
            scale = min(scale, 0.42)
        elif genre.depth_from_music <= 2:
            scale = min(scale, 1.15)
        elif genre.has_playlist:
            scale = min(scale, 1.55)
        scale = max(0.28, min(2.0, scale))
        genre.lod_rank = rank
        genre.min_visible_scale = round(scale, 4)
        genre.show_scale = genre.min_visible_scale
        genre.hide_scale = round(max(0.05, genre.min_visible_scale - 0.15), 4)
        if scale <= 0.5:
            genre.lod_tier = 0
        elif scale <= 0.8:
            genre.lod_tier = 1
        elif scale <= 1.15:
            genre.lod_tier = 2
        elif scale <= 1.5:
            genre.lod_tier = 3
        elif scale < 2.0:
            genre.lod_tier = 4
        else:
            genre.lod_tier = 5


def _layout_quality(
    genres: list[SemanticGenre],
    edges: list[SemanticEdge],
    *,
    sample_size: int,
) -> tuple[dict[str, float | int], list[dict]]:
    if len(genres) < 2:
        return {}, []

    by_id = {genre.genre_id: genre for genre in genres}
    top_edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
    edge_weight_by_pair: dict[tuple[str, str], float] = {}
    for edge in edges:
        weight = _edge_layout_weight(edge, by_id)
        if weight <= 0:
            continue
        pair = tuple(sorted((edge.from_genre_id, edge.to_genre_id)))
        edge_weight_by_pair[pair] = max(edge_weight_by_pair.get(pair, 0.0), weight)
        top_edges[edge.from_genre_id].append((edge.to_genre_id, weight))
        top_edges[edge.to_genre_id].append((edge.from_genre_id, weight))

    overlap_total = 0.0
    overlap_count = 0
    alien_neighbors = 0
    edge_distances: list[float] = []
    samples: list[dict] = []
    high_priority = sorted(genres, key=lambda genre: (-genre.priority, genre.title.lower()))[
        : max(sample_size, 80)
    ]

    for genre in high_priority:
        coordinate_neighbors = sorted(
            (
                (
                    other.genre_id,
                    math.hypot(genre.x - other.x, genre.y - other.y),
                )
                for other in genres
                if other.genre_id != genre.genre_id
            ),
            key=lambda item: item[1],
        )[:8]
        edge_neighbors = sorted(top_edges.get(genre.genre_id, ()), key=lambda item: -item[1])[:8]
        edge_ids = {neighbor_id for neighbor_id, _ in edge_neighbors}
        coordinate_ids = {neighbor_id for neighbor_id, _ in coordinate_neighbors}
        if edge_ids:
            overlap_total += len(edge_ids & coordinate_ids) / len(edge_ids)
            overlap_count += 1
        for neighbor_id, _ in coordinate_neighbors:
            other = by_id[neighbor_id]
            pair = tuple(sorted((genre.genre_id, neighbor_id)))
            if (
                other.root_genre_id != genre.root_genre_id
                and edge_weight_by_pair.get(pair, 0.0) < 0.5
            ):
                alien_neighbors += 1
        for neighbor_id, _ in edge_neighbors[:5]:
            other = by_id[neighbor_id]
            edge_distances.append(math.hypot(genre.x - other.x, genre.y - other.y))

        if len(samples) < sample_size:
            samples.append(
                {
                    "title": genre.title,
                    "coordinate_neighbors": [
                        {
                            "title": by_id[neighbor_id].title,
                            "distance": round(distance, 1),
                        }
                        for neighbor_id, distance in coordinate_neighbors[:6]
                    ],
                    "edge_neighbors": [
                        {
                            "title": by_id[neighbor_id].title,
                            "weight": round(weight, 3),
                        }
                        for neighbor_id, weight in edge_neighbors[:6]
                    ],
                }
            )

    metrics: dict[str, float | int] = {
        "sampled_genres": len(high_priority),
        "neighbor_overlap": round(overlap_total / max(1, overlap_count), 4),
        "alien_neighbor_count": alien_neighbors,
        "avg_top_edge_distance": round(
            sum(edge_distances) / max(1, len(edge_distances)),
            2,
        ),
        "max_min_visible_scale": round(max(genre.min_visible_scale for genre in genres), 4),
        "lod_score_min": round(min(genre.lod_score for genre in genres), 6),
        "lod_score_max": round(max(genre.lod_score for genre in genres), 6),
    }
    return metrics, samples


def _layout(
    genres: list[SemanticGenre],
    edges: list[SemanticEdge],
    *,
    center_genre_id: str | None,
    iterations: int,
) -> None:
    if not genres:
        return
    by_id = {genre.genre_id: genre for genre in genres}
    positions = _initial_positions(genres, center_genre_id=center_genre_id)
    anchors = dict(positions)
    root_geometry = _root_geometry(genres, center_genre_id=center_genre_id)
    fixed = {center_genre_id} if center_genre_id else set()
    if not center_genre_id:
        fixed.update(genre.genre_id for genre in genres if genre.depth_from_music <= 2)

    sim_edges = sorted(
        (edge for edge in edges if _edge_layout_weight(edge, by_id) > 0),
        key=lambda edge: -_edge_layout_weight(edge, by_id),
    )[: max(1, len(genres) * 18)]
    temperature = 1.0
    for _ in range(iterations):
        dx: dict[str, float] = defaultdict(float)
        dy: dict[str, float] = defaultdict(float)

        for edge in sim_edges:
            layout_weight = _edge_layout_weight(edge, by_id)
            left = positions.get(edge.from_genre_id)
            right = positions.get(edge.to_genre_id)
            if left is None or right is None:
                continue
            vx = right[0] - left[0]
            vy = right[1] - left[1]
            distance = math.hypot(vx, vy) or 0.001
            desired = _edge_desired_distance(edge, by_id)
            force = (distance - desired) * 0.012 * layout_weight
            fx = (vx / distance) * force
            fy = (vy / distance) * force
            if edge.from_genre_id not in fixed:
                dx[edge.from_genre_id] += fx
                dy[edge.from_genre_id] += fy
            if edge.to_genre_id not in fixed:
                dx[edge.to_genre_id] -= fx
                dy[edge.to_genre_id] -= fy

        for genre in genres:
            if genre.genre_id in fixed:
                continue
            x, y = positions[genre.genre_id]
            ax, ay = anchors[genre.genre_id]
            parent_id = _path_parent_id(genre)
            parent = positions.get(parent_id or "")
            root_angle, root_x, root_y = root_geometry.get(
                genre.root_genre_id,
                (_stable_unit(genre.root_genre_id) * math.tau, 0.0, 0.0),
            )
            anchor_strength = 0.028 if center_genre_id else 0.021
            dx[genre.genre_id] += (ax - x) * anchor_strength
            dy[genre.genre_id] += (ay - y) * anchor_strength

            if parent is not None:
                pvx = x - parent[0]
                pvy = y - parent[1]
                parent_distance = math.hypot(pvx, pvy) or 0.001
                desired_parent_distance = 70.0 + min(6, genre.depth_from_music) * 15.0
                parent_force = (parent_distance - desired_parent_distance) * 0.082
                dx[genre.genre_id] -= (pvx / parent_distance) * parent_force
                dy[genre.genre_id] -= (pvy / parent_distance) * parent_force

            territory_radius = 105.0 + max(0, genre.depth_from_music - 1) * 62.0
            territory_x = root_x + math.cos(root_angle) * territory_radius
            territory_y = root_y + math.sin(root_angle) * territory_radius * 0.72
            territory_strength = 0.005 if parent is not None else 0.026
            dx[genre.genre_id] += (territory_x - x) * territory_strength
            dy[genre.genre_id] += (territory_y - y) * territory_strength

            # Lightweight center repulsion keeps the broad roots readable
            # without running an O(n^2) force simulation.
            distance = math.hypot(x, y) or 1.0
            min_radius = 90.0 if center_genre_id else 150.0
            if distance < min_radius:
                push = (min_radius - distance) * 0.03
                dx[genre.genre_id] += (x / distance) * push
                dy[genre.genre_id] += (y / distance) * push

        max_step = 42.0 * temperature
        for genre in genres:
            if genre.genre_id in fixed:
                if center_genre_id and genre.genre_id == center_genre_id:
                    positions[genre.genre_id] = (0.0, 0.0)
                continue
            step_x = max(-max_step, min(max_step, dx.get(genre.genre_id, 0.0)))
            step_y = max(-max_step, min(max_step, dy.get(genre.genre_id, 0.0)))
            x, y = positions[genre.genre_id]
            positions[genre.genre_id] = (x + step_x, y + step_y)
        temperature *= 0.985

    if center_genre_id:
        offset_x, offset_y = positions.get(center_genre_id, (0.0, 0.0))
    else:
        if positions:
            weight_total = 0.0
            offset_x = 0.0
            offset_y = 0.0
            for genre in genres:
                weight = 1.0 + math.log10((genre.monthly_views_p30 or 0) + 10)
                x, y = positions[genre.genre_id]
                offset_x += x * weight
                offset_y += y * weight
                weight_total += weight
            offset_x /= weight_total or 1.0
            offset_y /= weight_total or 1.0
        else:
            offset_x = 0.0
            offset_y = 0.0

    for genre in genres:
        x, y = positions[genre.genre_id]
        genre.x = x - offset_x
        genre.y = y - offset_y
        if center_genre_id and genre.genre_id == center_genre_id:
            genre.x = 0.0
            genre.y = 0.0
    _pack_labels(genres)
    _assign_lod(genres, center_genre_id=center_genre_id)


async def _fetch_genres(conn: object, *, root_genre_id: str | None) -> list[SemanticGenre]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    WITH best_path AS (
                        SELECT DISTINCT ON (r.genre_id)
                            r.genre_id,
                            r.depth_from_music,
                            r.root_genre_id,
                            r.path_genre_ids,
                            root_g.wikipedia_title AS root_title
                        FROM wg_music_reachable_parents r
                        JOIN wg_genres g ON g.id = r.genre_id
                        JOIN wg_genres root_g ON root_g.id = r.root_genre_id
                        LEFT JOIN wg_genres parent_g ON parent_g.id = r.parent_genre_id
                        WHERE (
                            CAST(:root_genre_id AS text) IS NULL
                            OR r.genre_id = CAST(:root_genre_id AS text)
                            OR CAST(:root_genre_id AS text) = ANY(r.path_genre_ids)
                        )
                        ORDER BY
                            r.genre_id,
                            r.depth_from_music ASC,
                            CASE
                                WHEN CAST(:root_genre_id AS text) IS NULL
                                    AND root_g.wikipedia_title ~* '\\mmusic\\s+(of|in)\\M'
                                    THEN 1
                                ELSE 0
                            END,
                            CASE
                                WHEN lower(g.wikipedia_title) LIKE '%' || lower(
                                    regexp_replace(root_g.wikipedia_title, '\\s+music$', '', 'i')
                                ) || '%' THEN 0
                                WHEN parent_g.wikipedia_title IS NOT NULL
                                    AND lower(g.wikipedia_title) LIKE '%' || split_part(lower(
                                    regexp_replace(
                                        regexp_replace(
                                            COALESCE(parent_g.wikipedia_title, ''),
                                            '\\s+\\([^)]*\\)',
                                            '',
                                            'g'
                                        ),
                                        '\\s+music$',
                                        '',
                                        'i'
                                    )
                                ), ' ', 1) || '%' THEN 1
                                ELSE 2
                            END,
                            root_g.wikipedia_title
                    ),
                    playable AS (
                        SELECT genre_id, true AS has_playlist
                        FROM wg_genre_youtube_playlist_tracks
                        WHERE is_embeddable IS DISTINCT FROM false
                        GROUP BY genre_id
                    ),
                    child_counts AS (
                        SELECT
                            e.from_genre_id AS genre_id,
                            COUNT(DISTINCT e.to_genre_id) AS child_connection_count
                        FROM wg_edges e
                        JOIN wg_genres child_g ON child_g.id = e.to_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND child_g.deleted_at IS NULL
                          AND child_g.is_non_genre = false
                        GROUP BY e.from_genre_id
                    ),
                    parent_counts AS (
                        SELECT
                            e.to_genre_id AS genre_id,
                            COUNT(DISTINCT e.from_genre_id) AS parent_connection_count
                        FROM wg_edges e
                        JOIN wg_genres parent_g ON parent_g.id = e.from_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND parent_g.deleted_at IS NULL
                          AND parent_g.is_non_genre = false
                        GROUP BY e.to_genre_id
                    )
                    SELECT
                        g.id,
                        g.wikipedia_title,
                        g.summary,
                        g.monthly_views_p30,
                        bp.depth_from_music,
                        bp.root_genre_id,
                        bp.path_genre_ids,
                        bp.root_title,
                        COALESCE(p.has_playlist, false) AS has_playlist,
                        COALESCE(cc.child_connection_count, 0) AS child_connection_count,
                        COALESCE(pc.parent_connection_count, 0) AS parent_connection_count
                    FROM best_path bp
                    JOIN wg_genres g ON g.id = bp.genre_id
                    LEFT JOIN playable p ON p.genre_id = g.id
                    LEFT JOIN child_counts cc ON cc.genre_id = g.id
                    LEFT JOIN parent_counts pc ON pc.genre_id = g.id
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                      AND (
                          CAST(:root_genre_id AS text) IS NOT NULL
                          OR g.wikipedia_title !~* '\\mmusic\\s+(of|in)\\M'
                      )
                    ORDER BY bp.root_title, bp.depth_from_music, g.wikipedia_title
                """),
                {"root_genre_id": root_genre_id},
            )
        )
        .mappings()
        .fetchall()
    )
    center_genre_id = next(
        (
            row["id"]
            for row in rows
            if int(row["depth_from_music"]) == 0
        ),
        None,
    )
    rows = [
        row
        for row in rows
        if row["id"] == center_genre_id
        or not MUSIC_REGION_TITLE_RE.search(row["wikipedia_title"] or "")
    ]
    return [
        SemanticGenre(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            summary=row["summary"],
            monthly_views_p30=row["monthly_views_p30"],
            depth_from_music=row["depth_from_music"],
            root_genre_id=row["root_genre_id"],
            root_title=row["root_title"],
            path_genre_ids=tuple(row["path_genre_ids"] or ()),
            has_playlist=bool(row["has_playlist"]),
            child_connection_count=row["child_connection_count"],
            parent_connection_count=row["parent_connection_count"],
        )
        for row in rows
    ]


async def _fetch_region_genres(conn: object, *, region_id: str) -> list[SemanticGenre]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    WITH RECURSIVE region_tree AS (
                        SELECT
                            region.id AS region_id,
                            region.canonical_name,
                            region.kind,
                            promoted.genre_id AS promoted_genre_id,
                            promoted.wikipedia_title AS promoted_title,
                            0 AS region_depth
                        FROM wg_regions region
                        JOIN wg_region_promoted_genres promoted ON promoted.region_id = region.id
                        WHERE region.id = :region_id

                        UNION ALL

                        SELECT
                            child.id AS region_id,
                            child.canonical_name,
                            child.kind,
                            promoted.genre_id AS promoted_genre_id,
                            promoted.wikipedia_title AS promoted_title,
                            parent.region_depth + 1 AS region_depth
                        FROM region_tree parent
                        JOIN wg_region_relationships rel ON rel.to_region_id = parent.region_id
                        JOIN wg_regions child ON child.id = rel.from_region_id
                        JOIN wg_region_promoted_genres promoted ON promoted.region_id = child.id
                        WHERE rel.status = 'accepted'
                          AND parent.region_depth < 4
                          AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                              'collapsed',
                              'rejected',
                              'demoted_source',
                              'hidden_from_ui'
                          )
                    ),
                    center AS (
                        SELECT promoted_genre_id, promoted_title
                        FROM region_tree
                        WHERE region_id = :region_id
                        LIMIT 1
                    ),
                    related_genres AS (
                        SELECT DISTINCT ON (genre_id)
                            promoted_genre_id AS genre_id,
                            promoted_genre_id AS root_genre_id,
                            promoted_title AS root_title,
                            ARRAY[(SELECT promoted_genre_id FROM center), promoted_genre_id]::text[] AS path_genre_ids,
                            region_depth,
                            0 AS relation_rank
                        FROM region_tree
                        WHERE region_id = :region_id
                           OR promoted_title !~* '\\mmusic\\s+(of|in)\\M'

                        UNION

                        SELECT DISTINCT ON (edge.to_genre_id)
                            edge.to_genre_id AS genre_id,
                            coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)) AS root_genre_id,
                            coalesce(region_tree.promoted_title, (SELECT promoted_title FROM center)) AS root_title,
                            ARRAY[
                                (SELECT promoted_genre_id FROM center),
                                coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)),
                                edge.to_genre_id
                            ]::text[] AS path_genre_ids,
                            region_tree.region_depth + 1 AS region_depth,
                            1 AS relation_rank
                        FROM region_tree
                        JOIN wg_edges edge ON edge.from_genre_id = region_tree.promoted_genre_id
                        JOIN wg_genres child ON child.id = edge.to_genre_id
                        WHERE region_tree.region_id <> :region_id
                          AND region_tree.promoted_title ~* '\\mmusic\\s+(of|in)\\M'
                          AND edge.is_ignored = false
                          AND edge.to_genre_id IS NOT NULL
                          AND child.deleted_at IS NULL
                          AND child.is_non_genre = false

                        UNION

                        SELECT DISTINCT ON (rel.genre_id)
                            rel.genre_id,
                            coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)) AS root_genre_id,
                            coalesce(region_tree.promoted_title, (SELECT promoted_title FROM center)) AS root_title,
                            CASE
                                WHEN region_tree.promoted_genre_id = rel.genre_id THEN
                                    ARRAY[(SELECT promoted_genre_id FROM center), rel.genre_id]::text[]
                                ELSE
                                    ARRAY[
                                        (SELECT promoted_genre_id FROM center),
                                        coalesce(region_tree.promoted_genre_id, (SELECT promoted_genre_id FROM center)),
                                        rel.genre_id
                                    ]::text[]
                            END AS path_genre_ids,
                            region_tree.region_depth + 1 AS region_depth,
                            1 AS relation_rank
                        FROM region_tree
                        JOIN wg_region_genre_relationships rel ON rel.region_id = region_tree.region_id
                        WHERE rel.status = 'accepted'
                          AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')

                        UNION

                        SELECT DISTINCT ON (affinity.genre_id)
                            affinity.genre_id,
                            (SELECT promoted_genre_id FROM center) AS root_genre_id,
                            (SELECT promoted_title FROM center) AS root_title,
                            ARRAY[
                                (SELECT promoted_genre_id FROM center),
                                affinity.genre_id
                            ]::text[] AS path_genre_ids,
                            2 AS region_depth,
                            2 AS relation_rank
                        FROM wg_genre_country_affinities affinity
                        WHERE affinity.region_id = :region_id
                          AND affinity.review_status <> 'rejected'
                          AND affinity.score >= 0.55
                          AND affinity.confidence >= 0.50
                    ),
                    playable AS (
                        SELECT genre_id, true AS has_playlist
                        FROM wg_genre_youtube_playlist_tracks
                        WHERE is_embeddable IS DISTINCT FROM false
                        GROUP BY genre_id
                    ),
                    child_counts AS (
                        SELECT
                            e.from_genre_id AS genre_id,
                            COUNT(DISTINCT e.to_genre_id) AS child_connection_count
                        FROM wg_edges e
                        JOIN wg_genres child_g ON child_g.id = e.to_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND child_g.deleted_at IS NULL
                          AND child_g.is_non_genre = false
                        GROUP BY e.from_genre_id
                    ),
                    parent_counts AS (
                        SELECT
                            e.to_genre_id AS genre_id,
                            COUNT(DISTINCT e.from_genre_id) AS parent_connection_count
                        FROM wg_edges e
                        JOIN wg_genres parent_g ON parent_g.id = e.from_genre_id
                        WHERE e.to_genre_id IS NOT NULL
                          AND e.is_ignored = false
                          AND parent_g.deleted_at IS NULL
                          AND parent_g.is_non_genre = false
                        GROUP BY e.to_genre_id
                    ),
                    best_path AS (
                        SELECT DISTINCT ON (genre_id)
                            genre_id,
                            root_genre_id,
                            root_title,
                            path_genre_ids,
                            region_depth,
                            relation_rank
                        FROM related_genres
                        ORDER BY genre_id, relation_rank, region_depth, root_title
                    )
                    SELECT
                        g.id,
                        g.wikipedia_title,
                        g.summary,
                        g.monthly_views_p30,
                        CASE
                            WHEN g.id = (SELECT promoted_genre_id FROM center) THEN 0
                            ELSE greatest(1, best_path.region_depth + 1)
                        END AS depth_from_music,
                        best_path.root_genre_id,
                        best_path.root_title,
                        best_path.path_genre_ids,
                        COALESCE(p.has_playlist, false) AS has_playlist,
                        COALESCE(cc.child_connection_count, 0) AS child_connection_count,
                        COALESCE(pc.parent_connection_count, 0) AS parent_connection_count
                    FROM best_path
                    JOIN wg_genres g ON g.id = best_path.genre_id
                    LEFT JOIN playable p ON p.genre_id = g.id
                    LEFT JOIN child_counts cc ON cc.genre_id = g.id
                    LEFT JOIN parent_counts pc ON pc.genre_id = g.id
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                      AND (
                          g.id = (SELECT promoted_genre_id FROM center)
                          OR g.wikipedia_title !~* '\\mmusic\\s+(of|in)\\M'
                      )
                    ORDER BY depth_from_music, best_path.root_title, g.wikipedia_title
                """),
                {"region_id": region_id},
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        SemanticGenre(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            summary=row["summary"],
            monthly_views_p30=row["monthly_views_p30"],
            depth_from_music=row["depth_from_music"],
            root_genre_id=row["root_genre_id"],
            root_title=row["root_title"],
            path_genre_ids=tuple(row["path_genre_ids"] or ()),
            has_playlist=bool(row["has_playlist"]),
            child_connection_count=row["child_connection_count"],
            parent_connection_count=row["parent_connection_count"],
        )
        for row in rows
    ]


async def _fetch_grouped_values(
    conn: object,
    kind: str,
    genre_ids: list[str],
) -> dict[str, list[str]]:
    if not genre_ids:
        return {}
    queries = {
        "aliases": """
            SELECT genre_id, alias AS value
            FROM wg_aliases
            WHERE genre_id = ANY(:genre_ids)
            ORDER BY genre_id, value
        """,
        "categories": """
            SELECT genre_id, category AS value
            FROM wg_categories
            WHERE genre_id = ANY(:genre_ids)
            ORDER BY genre_id, value
        """,
        "origins": """
            SELECT genre_id, value
            FROM wg_origins
            WHERE genre_id = ANY(:genre_ids)
            ORDER BY genre_id, value
        """,
        "instruments": """
            SELECT genre_id, instrument AS value
            FROM wg_instruments
            WHERE genre_id = ANY(:genre_ids)
            ORDER BY genre_id, value
        """,
    }
    query = queries[kind]
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text(query),
                {"genre_ids": genre_ids},
            )
        )
        .mappings()
        .fetchall()
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["value"]:
            grouped[row["genre_id"]].append(row["value"])
    return grouped


async def _fetch_playlist_terms(conn: object, genre_ids: list[str]) -> dict[str, list[str]]:
    if not genre_ids:
        return {}
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT genre_id, song_title, artist
                    FROM wg_genre_youtube_playlist_tracks
                    WHERE genre_id = ANY(:genre_ids)
                      AND is_embeddable IS DISTINCT FROM false
                    ORDER BY genre_id, ordinal
                """),
                {"genre_ids": genre_ids},
            )
        )
        .mappings()
        .fetchall()
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        value = " ".join(part for part in (row["song_title"], row["artist"]) if part)
        if value:
            grouped[row["genre_id"]].append(value)
    return grouped


async def _fetch_raw_graph_edges(conn: object, genre_ids: list[str]) -> list[dict]:
    if not genre_ids:
        return []
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
                    SELECT
                        e.from_genre_id,
                        e.to_genre_id,
                        e.relation,
                        e.evidence_relation,
                        e.source
                    FROM wg_edges e
                    JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                    JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                    WHERE e.from_genre_id = ANY(:genre_ids)
                      AND e.to_genre_id = ANY(:genre_ids)
                      AND e.to_genre_id IS NOT NULL
                      AND e.is_ignored = false
                      AND from_g.deleted_at IS NULL
                      AND from_g.is_non_genre = false
                      AND to_g.deleted_at IS NULL
                      AND to_g.is_non_genre = false
                      AND (
                          e.relation = ANY(:display_relations)
                          OR (
                              e.relation = :related_relation
                              AND e.evidence_relation = ANY(:display_relations)
                          )
                      )
                """),
                {
                    "genre_ids": genre_ids,
                    "display_relations": list(RELATION_WEIGHT),
                    "related_relation": "related_genre",
                },
            )
        )
        .mappings()
        .fetchall()
    )
    return [dict(row) for row in rows]


def _apply_grouped_values(
    genres: list[SemanticGenre],
    grouped: dict[str, dict[str, list[str]]],
) -> None:
    for genre in genres:
        values = grouped.get(genre.genre_id, {})
        genre.aliases = values.get("aliases", [])
        genre.categories = values.get("categories", [])
        genre.origins = values.get("origins", [])
        genre.instruments = values.get("instruments", [])
        genre.playlist_terms = values.get("playlist_terms", [])


async def build_semantic_cloud_layout(
    *,
    root_genre_id: str | None = None,
    region_id: str | None = None,
    dry_run: bool = False,
    sample_size: int = 20,
    iterations: int = 90,
) -> SemanticCloudLayoutStats:
    """Rebuild one semantic cloud layout scope."""
    await apply_migrations()
    engine = get_engine()
    layout_key = layout_key_for_root(root_genre_id, region_id=region_id)
    stats = SemanticCloudLayoutStats(layout_key=layout_key, dry_run=dry_run)

    async with engine.connect() as conn:
        genres = (
            await _fetch_region_genres(conn, region_id=region_id)
            if region_id
            else await _fetch_genres(conn, root_genre_id=root_genre_id)
        )
        genre_ids = [genre.genre_id for genre in genres]
        stats.total_genres = len(genres)

        aliases = await _fetch_grouped_values(conn, "aliases", genre_ids)
        categories = await _fetch_grouped_values(conn, "categories", genre_ids)
        origins = await _fetch_grouped_values(conn, "origins", genre_ids)
        instruments = await _fetch_grouped_values(conn, "instruments", genre_ids)
        playlist_terms = await _fetch_playlist_terms(conn, genre_ids)
        raw_graph_edges = await _fetch_raw_graph_edges(conn, genre_ids)

    grouped = {
        genre_id: {
            "aliases": aliases.get(genre_id, []),
            "categories": categories.get(genre_id, []),
            "origins": origins.get(genre_id, []),
            "instruments": instruments.get(genre_id, []),
            "playlist_terms": playlist_terms.get(genre_id, []),
        }
        for genre_id in genre_ids
    }
    _apply_grouped_values(genres, grouped)

    documents = _build_vectors(genres)
    semantic_edges = _semantic_edges(genres)
    graph_edges = _graph_edges(raw_graph_edges, set(genre_ids))
    merged_edges = _merge_edges([*semantic_edges, *graph_edges])
    stats.vector_rows = len(genres)
    stats.semantic_edges = len(semantic_edges)
    stats.graph_edges = len(graph_edges)
    stats.materialized_edges = len(merged_edges)

    center_genre_id = root_genre_id if root_genre_id else None
    if region_id and genres:
        center_genre_id = min(
            genres,
            key=lambda genre: (
                genre.depth_from_music,
                genre.root_title.lower(),
                genre.title.lower(),
            ),
        ).genre_id
    _layout(genres, merged_edges, center_genre_id=center_genre_id, iterations=iterations)
    quality_metrics, quality_sample = _layout_quality(
        genres,
        merged_edges,
        sample_size=min(sample_size, 20),
    )
    stats.layout_rows = len(genres)
    stats.quality_metrics = quality_metrics
    stats.quality_sample = quality_sample
    stats.sample = [
        {
            "title": genre.title,
            "x": round(genre.x, 1),
            "y": round(genre.y, 1),
            "root": genre.root_title,
            "terms": list(genre.vector)[:6],
        }
        for genre in sorted(
            genres,
            key=lambda row: (-row.priority, row.title.lower()),
        )[:sample_size]
    ]

    if dry_run:
        logger.info(
            "semantic_cloud_layout_dry_run",
            layout_key=layout_key,
            total_genres=stats.total_genres,
            semantic_edges=stats.semantic_edges,
            graph_edges=stats.graph_edges,
        )
        return stats

    async with engine.begin() as conn:
        deleted_layouts = await conn.execute(
            text("DELETE FROM wg_genre_semantic_layouts WHERE layout_key = :layout_key"),
            {"layout_key": layout_key},
        )
        deleted_edges = await conn.execute(
            text("DELETE FROM wg_genre_semantic_edges WHERE layout_key = :layout_key"),
            {"layout_key": layout_key},
        )
        deleted_vectors = await conn.execute(
            text("DELETE FROM wg_genre_semantic_vectors WHERE layout_key = :layout_key"),
            {"layout_key": layout_key},
        )
        stats.deleted_layouts = int(deleted_layouts.rowcount or 0)
        stats.deleted_edges = int(deleted_edges.rowcount or 0)
        stats.deleted_vectors = int(deleted_vectors.rowcount or 0)

        if genres:
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_semantic_vectors (
                        layout_key,
                        genre_id,
                        document_text,
                        terms,
                        vector,
                        metadata,
                        vector_version,
                        indexed_at
                    )
                    VALUES (
                        :layout_key,
                        :genre_id,
                        :document_text,
                        CAST(:terms AS jsonb),
                        CAST(:vector AS jsonb),
                        CAST(:metadata AS jsonb),
                        :vector_version,
                        now()
                    )
                """),
                [
                    {
                        "layout_key": layout_key,
                        "genre_id": genre.genre_id,
                        "document_text": documents.get(genre.genre_id, ""),
                        "terms": json.dumps(dict(genre.terms.most_common(80)), sort_keys=True),
                        "vector": json.dumps(genre.vector, sort_keys=True),
                        "metadata": json.dumps(
                            {
                                "title": genre.title,
                                "root_genre_id": genre.root_genre_id,
                                "root_title": genre.root_title,
                                "depth_from_music": genre.depth_from_music,
                                "has_playlist": genre.has_playlist,
                            },
                            sort_keys=True,
                        ),
                        "vector_version": VECTOR_VERSION,
                    }
                    for genre in genres
                ],
            )
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_semantic_layouts (
                        layout_key,
                        genre_id,
                        x,
                        y,
                        width,
                        height,
                        text_width,
                        text_height,
                        box_width,
                        box_height,
                        box_pad_x,
                        box_pad_y,
                        priority,
                        is_center,
                        lod_score,
                        min_visible_scale,
                        show_scale,
                        hide_scale,
                        lod_rank,
                        lod_tier,
                        metadata,
                        layout_version,
                        indexed_at
                    )
                    VALUES (
                        :layout_key,
                        :genre_id,
                        :x,
                        :y,
                        :width,
                        :height,
                        :text_width,
                        :text_height,
                        :box_width,
                        :box_height,
                        :box_pad_x,
                        :box_pad_y,
                        :priority,
                        :is_center,
                        :lod_score,
                        :min_visible_scale,
                        :show_scale,
                        :hide_scale,
                        :lod_rank,
                        :lod_tier,
                        CAST(:metadata AS jsonb),
                        :layout_version,
                        now()
                    )
                """),
                [
                    {
                        "layout_key": layout_key,
                        "genre_id": genre.genre_id,
                        "x": genre.x,
                        "y": genre.y,
                        "width": genre.width,
                        "height": genre.height,
                        "text_width": genre.text_width,
                        "text_height": genre.text_height,
                        "box_width": genre.box_width,
                        "box_height": genre.box_height,
                        "box_pad_x": genre.box_pad_x,
                        "box_pad_y": genre.box_pad_y,
                        "priority": genre.priority,
                        "is_center": genre.genre_id == center_genre_id,
                        "lod_score": genre.lod_score,
                        "min_visible_scale": genre.min_visible_scale,
                        "show_scale": genre.show_scale,
                        "hide_scale": genre.hide_scale,
                        "lod_rank": genre.lod_rank,
                        "lod_tier": genre.lod_tier,
                        "metadata": json.dumps(
                            {
                                "root_genre_id": genre.root_genre_id,
                                "root_title": genre.root_title,
                                "depth_from_music": genre.depth_from_music,
                                "lod_score": genre.lod_score,
                                "lod_rank": genre.lod_rank,
                            },
                            sort_keys=True,
                        ),
                        "layout_version": LAYOUT_VERSION,
                    }
                    for genre in genres
                ],
            )

        if merged_edges:
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_semantic_edges (
                        layout_key,
                        from_genre_id,
                        to_genre_id,
                        weight,
                        sources,
                        edge_version,
                        indexed_at
                    )
                    VALUES (
                        :layout_key,
                        :from_genre_id,
                        :to_genre_id,
                        :weight,
                        CAST(:sources AS jsonb),
                        :edge_version,
                        now()
                    )
                """),
                [
                    {
                        "layout_key": layout_key,
                        "from_genre_id": edge.from_genre_id,
                        "to_genre_id": edge.to_genre_id,
                        "weight": edge.weight,
                        "sources": json.dumps(edge.sources, sort_keys=True),
                        "edge_version": EDGE_VERSION,
                    }
                    for edge in merged_edges
                ],
            )

        await conn.execute(
            text("""
                INSERT INTO wg_genre_semantic_layout_runs (
                    layout_key,
                    layout_version,
                    vector_version,
                    edge_version,
                    metrics,
                    sample,
                    indexed_at
                )
                VALUES (
                    :layout_key,
                    :layout_version,
                    :vector_version,
                    :edge_version,
                    CAST(:metrics AS jsonb),
                    CAST(:sample AS jsonb),
                    now()
                )
                ON CONFLICT (layout_key, layout_version) DO UPDATE SET
                    vector_version = EXCLUDED.vector_version,
                    edge_version = EXCLUDED.edge_version,
                    metrics = EXCLUDED.metrics,
                    sample = EXCLUDED.sample,
                    indexed_at = now()
            """),
            {
                "layout_key": layout_key,
                "layout_version": LAYOUT_VERSION,
                "vector_version": VECTOR_VERSION,
                "edge_version": EDGE_VERSION,
                "metrics": json.dumps(stats.quality_metrics, sort_keys=True),
                "sample": json.dumps(stats.quality_sample, sort_keys=True),
            },
        )
        await refresh_cloud_display_cache(conn, layout_key=layout_key)

    logger.info(
        "semantic_cloud_layout_complete",
        layout_key=layout_key,
        total_genres=stats.total_genres,
        semantic_edges=stats.semantic_edges,
        graph_edges=stats.graph_edges,
        layout_rows=stats.layout_rows,
    )
    return stats
