"""Materialize graph-similarity colors for genres.

The explorer uses these colors as a compact visual embedding: each genre gets a
root-affinity vector over broad Music children, then that vector is mixed in a
perceptual color space.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.cycle_guard import (
    DEFAULT_ROOT_TITLES,
    DISPLAY_RELATIONS,
    RELATED_RELATION,
)

logger = structlog.get_logger(__name__)

BASIS_VERSION = "root-affinity-oklab-v1"

ROOT_COLOR_BY_TITLE = {
    "Rock music": "#c44e35",
    "Pop music": "#d85a9e",
    "Hip hop music": "#d8872d",
    "Electronic music": "#2397aa",
    "Jazz": "#6b63bd",
    "Classical music": "#8f7049",
    "Rhythm and blues": "#b34f78",
    "Country music": "#78a34a",
    "Folk music": "#aa7a3c",
    "Blues": "#426fb0",
    "Heavy metal music": "#5c5d67",
    "Reggae": "#4d9c4a",
    "World music": "#27977f",
    "Latin music": "#d26f3f",
    "Soundtrack": "#7d72a8",
    "Experimental music": "#c9654f",
    "Religious music": "#8589c8",
}

RELATION_WEIGHT = {
    "broader_genres": 1.0,
    "subgenres": 1.0,
    "subgenre": 1.0,
    "source_genres": 0.42,
    "derived_genres": 0.76,
    "derivative": 0.76,
    "fusion_components": 0.68,
    "fusion_descendants": 0.68,
    "fusion_genre": 0.68,
    "regional_variations": 0.72,
    "regional_scene": 0.58,
}

SOURCE_WEIGHT = {
    "gpt_review": 1.18,
    "manual_curation": 1.1,
    "infobox": 1.0,
    "wikidata": 0.9,
    "inbound_index": 0.72,
}

REVERSE_RELATION_WEIGHT = {
    "broader_genres": 0.34,
    "subgenres": 0.34,
    "subgenre": 0.34,
    "source_genres": 0.20,
    "derived_genres": 0.28,
    "derivative": 0.28,
    "fusion_components": 0.26,
    "fusion_descendants": 0.26,
    "fusion_genre": 0.26,
    "regional_variations": 0.82,
    "regional_scene": 0.82,
}

ELECTRONIC_DIRECT_ROOT_AFFINITY_FLOOR = 0.50
ELECTRONIC_ROOT_TITLE = "Electronic music"


@dataclass(frozen=True)
class ColorGenre:
    genre_id: str
    title: str
    monthly_views_p30: int | None = None


@dataclass(frozen=True)
class ColorRoot:
    genre_id: str
    title: str
    color_hex: str


@dataclass(frozen=True)
class ColorEdge:
    from_genre_id: str
    to_genre_id: str
    relation: str
    source: str
    evidence_relation: str | None = None
    block_forward: bool = False
    block_reverse: bool = False

    @property
    def effective_relation(self) -> str:
        if self.relation == RELATED_RELATION and self.evidence_relation in DISPLAY_RELATIONS:
            return self.evidence_relation
        return self.relation

    @property
    def weight(self) -> float:
        return RELATION_WEIGHT.get(self.effective_relation, 0.0) * SOURCE_WEIGHT.get(
            self.source, 0.82
        )

    @property
    def reverse_weight(self) -> float:
        return REVERSE_RELATION_WEIGHT.get(
            self.effective_relation, 0.0
        ) * SOURCE_WEIGHT.get(self.source, 0.82)


@dataclass(frozen=True)
class GenreColor:
    genre_id: str
    title: str
    color_hex: str
    confidence: float
    root_affinity: dict[str, float]


@dataclass(frozen=True)
class ColorContribution:
    from_genre_id: str
    weight: float


@dataclass
class GenreColorStats:
    roots_requested: int = 0
    roots_found: int = 0
    roots_missing: list[str] = field(default_factory=list)
    total_genres: int = 0
    edges_scanned: int = 0
    colored_genres: int = 0
    deleted_existing: int = 0
    dry_run: bool = False
    sample: list[GenreColor] = field(default_factory=list)


def _srgb_channel_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_channel_to_srgb(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * 12.92 if value <= 0.0031308 else 1.055 * (value ** (1 / 2.4)) - 0.055


def _hex_to_srgb(color: str) -> tuple[float, float, float]:
    color = color.removeprefix("#")
    return (
        int(color[0:2], 16) / 255,
        int(color[2:4], 16) / 255,
        int(color[4:6], 16) / 255,
    )


def _srgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0, min(1, channel)) * 255):02x}" for channel in rgb)


def _srgb_to_oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_srgb_channel_to_linear(channel) for channel in rgb)
    long = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    medium = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    long_ = math.copysign(abs(long) ** (1 / 3), long)
    medium_ = math.copysign(abs(medium) ** (1 / 3), medium)
    short_ = math.copysign(abs(short) ** (1 / 3), short)
    return (
        0.2104542553 * long_ + 0.7936177850 * medium_ - 0.0040720468 * short_,
        1.9779984951 * long_ - 2.4285922050 * medium_ + 0.4505937099 * short_,
        0.0259040371 * long_ + 0.7827717662 * medium_ - 0.8086757660 * short_,
    )


def _oklab_to_srgb(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    lightness, a, b = lab
    long_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    medium_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    short_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    long3 = long_**3
    medium3 = medium_**3
    short3 = short_**3
    r = +4.0767416621 * long3 - 3.3077115913 * medium3 + 0.2309699292 * short3
    g = -1.2684380046 * long3 + 2.6097574011 * medium3 - 0.3413193965 * short3
    blue = -0.0041960863 * long3 - 0.7034186147 * medium3 + 1.7076147010 * short3
    return (
        _linear_channel_to_srgb(r),
        _linear_channel_to_srgb(g),
        _linear_channel_to_srgb(blue),
    )


def _normalize(vector: dict[str, float]) -> dict[str, float]:
    total = sum(value for value in vector.values() if value > 0)
    if total <= 0:
        return {}
    return {key: value / total for key, value in vector.items() if value > 0}


def _mix_vectors(items: list[tuple[dict[str, float], float]]) -> dict[str, float]:
    mixed: dict[str, float] = defaultdict(float)
    for vector, weight in items:
        if weight <= 0:
            continue
        for key, value in vector.items():
            mixed[key] += value * weight
    return _normalize(dict(mixed))


def _apply_direct_root_floor(
    vector: dict[str, float],
    direct_roots: list[tuple[str, float]],
    *,
    floor: float = ELECTRONIC_DIRECT_ROOT_AFFINITY_FLOOR,
) -> dict[str, float]:
    """Keep direct Electronic children modestly tied to Electronic."""
    if not vector or not direct_roots:
        return vector

    direct_weight = sum(max(0.0, weight) for _, weight in direct_roots)
    if direct_weight <= 0:
        return vector

    normalized_direct = {
        root_id: weight / direct_weight
        for root_id, weight in direct_roots
        if weight > 0
    }
    current_direct = sum(vector.get(root_id, 0.0) for root_id in normalized_direct)
    if current_direct >= floor:
        return vector

    mixed = defaultdict(float)
    for root_id, value in vector.items():
        mixed[root_id] += value * (1 - floor)
    for root_id, value in normalized_direct.items():
        mixed[root_id] += value * floor
    return _normalize(dict(mixed))


def _confidence(vector: dict[str, float], total_weight: float, monthly_views: int | None) -> float:
    if not vector:
        return 0.0
    ordered = sorted(vector.values(), reverse=True)
    top = ordered[0]
    support = 1 - math.exp(-max(0.0, total_weight) / 1.35)
    views = math.log10(max(0, monthly_views or 0) + 1) / 6
    confidence = 0.14 + support * 0.56 + top * 0.14 + min(1.0, views) * 0.16
    return max(0.0, min(1.0, confidence))


def _color_from_affinity(
    affinity: dict[str, float],
    root_lab: dict[str, tuple[float, float, float]],
    confidence: float,
) -> str:
    if not affinity:
        return "#8b8f96"

    top_items = sorted(affinity.items(), key=lambda item: item[1], reverse=True)[:4]
    total = sum(value for _, value in top_items)
    lightness = 0.0
    a = 0.0
    b = 0.0
    for root_id, weight in top_items:
        rw = weight / total
        rl, ra, rb = root_lab[root_id]
        lightness += rl * rw
        a += ra * rw
        b += rb * rw

    # Keep graph labels readable and let confidence control color intensity.
    lightness = max(0.56, min(0.74, lightness))
    chroma_scale = 0.52 + confidence * 0.42
    return _srgb_to_hex(_oklab_to_srgb((lightness, a * chroma_scale, b * chroma_scale)))


def compute_genre_colors(
    genres: list[ColorGenre],
    roots: list[ColorRoot],
    edges: list[ColorEdge],
    *,
    iterations: int = 30,
    sample_size: int = 25,
) -> tuple[list[GenreColor], list[GenreColor]]:
    """Compute root-affinity colors from active display edges."""
    genre_by_id = {genre.genre_id: genre for genre in genres}
    root_by_id = {root.genre_id: root for root in roots}
    incoming: dict[str, list[ColorContribution]] = defaultdict(list)
    incoming_weight: dict[str, float] = defaultdict(float)
    direct_root_incoming: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for edge in edges:
        if edge.from_genre_id not in genre_by_id or edge.to_genre_id not in genre_by_id:
            continue
        if not edge.block_forward and edge.weight > 0:
            incoming[edge.to_genre_id].append(
                ColorContribution(edge.from_genre_id, edge.weight)
            )
            incoming_weight[edge.to_genre_id] += edge.weight
            if (
                edge.from_genre_id in root_by_id
                and root_by_id[edge.from_genre_id].title == ELECTRONIC_ROOT_TITLE
            ):
                direct_root_incoming[edge.to_genre_id].append(
                    (edge.from_genre_id, edge.weight)
                )
        if not edge.block_reverse and edge.reverse_weight > 0:
            incoming[edge.from_genre_id].append(
                ColorContribution(edge.to_genre_id, edge.reverse_weight)
            )
            incoming_weight[edge.from_genre_id] += edge.reverse_weight

    vectors: dict[str, dict[str, float]] = {
        genre.genre_id: ({genre.genre_id: 1.0} if genre.genre_id in root_by_id else {})
        for genre in genres
    }

    for _ in range(iterations):
        next_vectors: dict[str, dict[str, float]] = {}
        for genre in genres:
            if genre.genre_id in root_by_id:
                next_vectors[genre.genre_id] = {genre.genre_id: 1.0}
                continue

            contributions = [
                (vectors.get(contribution.from_genre_id, {}), contribution.weight)
                for contribution in incoming.get(genre.genre_id, ())
                if vectors.get(contribution.from_genre_id)
            ]
            if not contributions:
                next_vectors[genre.genre_id] = vectors.get(genre.genre_id, {})
                continue

            if vectors.get(genre.genre_id):
                contributions.append((vectors[genre.genre_id], 0.05))
            next_vectors[genre.genre_id] = _mix_vectors(contributions)

        vectors = next_vectors

    root_lab = {root.genre_id: _srgb_to_oklab(_hex_to_srgb(root.color_hex)) for root in roots}
    root_title_by_id = {root.genre_id: root.title for root in roots}

    rows: list[GenreColor] = []
    for genre in genres:
        vector = _normalize(vectors.get(genre.genre_id, {}))
        if genre.genre_id not in root_by_id:
            vector = _apply_direct_root_floor(
                vector,
                direct_root_incoming.get(genre.genre_id, []),
            )
        if not vector:
            continue
        if genre.genre_id in root_by_id:
            confidence = 1.0
        else:
            confidence = _confidence(
                vector,
                incoming_weight.get(genre.genre_id, 0.0),
                genre.monthly_views_p30,
            )

        root_affinity = {
            root_title_by_id[root_id]: round(value, 4)
            for root_id, value in sorted(vector.items(), key=lambda item: item[1], reverse=True)
            if value >= 0.01
        }
        rows.append(
            GenreColor(
                genre_id=genre.genre_id,
                title=genre.title,
                color_hex=_color_from_affinity(vector, root_lab, confidence),
                confidence=round(confidence, 4),
                root_affinity=root_affinity,
            )
        )

    rows.sort(key=lambda row: (row.title.lower(), row.genre_id))
    sample = sorted(rows, key=lambda row: (-row.confidence, row.title.lower()))[:sample_size]
    return rows, sample


def _root_color(title: str) -> str:
    return ROOT_COLOR_BY_TITLE.get(title, "#8b8f96")


async def _resolve_roots(
    conn: object,
    root_titles: tuple[str, ...],
) -> tuple[list[ColorRoot], list[str]]:
    direct_rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
            SELECT wikipedia_title, id
            FROM wg_genres
            WHERE wikipedia_title = ANY(:titles)
              AND deleted_at IS NULL
              AND is_non_genre = false
        """),
                {"titles": list(root_titles)},
            )
        )
        .mappings()
        .fetchall()
    )
    id_by_title = {row["wikipedia_title"]: row["id"] for row in direct_rows}

    missing_direct = [title for title in root_titles if title not in id_by_title]
    if missing_direct:
        redirect_rows = (
            (
                await conn.execute(  # type: ignore[attr-defined]
                    text("""
                SELECT r.from_title, r.to_genre_id
                FROM wg_redirects r
                JOIN wg_genres g ON g.id = r.to_genre_id
                WHERE r.from_title = ANY(:titles)
                  AND g.deleted_at IS NULL
                  AND g.is_non_genre = false
            """),
                    {"titles": missing_direct},
                )
            )
            .mappings()
            .fetchall()
        )
        for row in redirect_rows:
            id_by_title[row["from_title"]] = row["to_genre_id"]

    roots: list[ColorRoot] = []
    missing: list[str] = []
    for title in root_titles:
        root_id = id_by_title.get(title)
        if root_id:
            roots.append(ColorRoot(root_id, title, _root_color(title)))
        else:
            missing.append(title)
    return roots, missing


async def index_genre_colors(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
    root_titles: tuple[str, ...] = DEFAULT_ROOT_TITLES,
) -> GenreColorStats:
    """Rebuild ``wg_genre_colors`` from active display relationships."""
    await apply_migrations()
    engine = get_engine()
    stats = GenreColorStats(
        roots_requested=len(root_titles),
        dry_run=dry_run,
    )

    async with engine.connect() as conn:
        roots, missing = await _resolve_roots(conn, root_titles)
        stats.roots_found = len(roots)
        stats.roots_missing = missing
        regional_rows = (
            (
                await conn.execute(
                    text("""
                        SELECT DISTINCT genre_id
                        FROM wg_region_promoted_genres
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        regional_genre_ids = {row["genre_id"] for row in regional_rows}

        genre_rows = (
            (
                await conn.execute(
                    text("""
                SELECT id, wikipedia_title, monthly_views_p30
                FROM wg_genres
                WHERE deleted_at IS NULL
                  AND is_non_genre = false
                ORDER BY wikipedia_title
            """)
                )
            )
            .mappings()
            .fetchall()
        )

        edge_rows = (
            (
                await conn.execute(
                    text("""
                SELECT e.from_genre_id,
                       e.to_genre_id,
                       e.relation,
                       e.evidence_relation,
                       e.source
                FROM wg_relationship_traversal_edges e
                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                WHERE e.to_genre_id IS NOT NULL
                  AND (
                    e.relation = ANY(:relations)
                    OR e.relation = ANY(:color_only_relations)
                    OR (
                      e.relation = :related_relation
                      AND e.evidence_relation = ANY(:relations)
                    )
                  )
                  AND e.is_ignored = false
                  AND from_g.deleted_at IS NULL
                  AND from_g.is_non_genre = false
                  AND to_g.deleted_at IS NULL
                  AND to_g.is_non_genre = false
            """),
                    {
                        "relations": list(DISPLAY_RELATIONS),
                        "color_only_relations": ["regional_scene"],
                        "related_relation": RELATED_RELATION,
                    },
                )
            )
            .mappings()
            .fetchall()
        )

    genres = [
        ColorGenre(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            monthly_views_p30=row["monthly_views_p30"],
        )
        for row in genre_rows
    ]
    edges = [
        ColorEdge(
            from_genre_id=row["from_genre_id"],
            to_genre_id=row["to_genre_id"],
            relation=row["relation"],
            evidence_relation=row["evidence_relation"],
            source=row["source"],
            # Prevent regional (Music of ...) interconnections from washing out
            # non-regional genres: allow nonregional -> regional, but block
            # regional -> nonregional affinity flow.
            block_forward=(
                row["from_genre_id"] in regional_genre_ids
                and row["to_genre_id"] not in regional_genre_ids
            ),
        )
        for row in edge_rows
    ]
    stats.total_genres = len(genres)
    stats.edges_scanned = len(edges)

    color_rows, sample = compute_genre_colors(
        genres,
        roots,
        edges,
        sample_size=sample_size,
    )
    stats.colored_genres = len(color_rows)
    stats.sample = sample

    if dry_run:
        logger.info(
            "genre_colors_dry_run",
            total_genres=stats.total_genres,
            colored_genres=stats.colored_genres,
            edges_scanned=stats.edges_scanned,
        )
        return stats

    async with engine.begin() as conn:
        deleted = await conn.execute(text("DELETE FROM wg_genre_colors"))
        stats.deleted_existing = int(deleted.rowcount or 0)

        if color_rows:
            await conn.execute(
                text("""
                    INSERT INTO wg_genre_colors (
                        genre_id,
                        color_hex,
                        confidence,
                        root_affinity,
                        basis_version,
                        indexed_at
                    )
                    VALUES (
                        :genre_id,
                        :color_hex,
                        :confidence,
                        CAST(:root_affinity AS jsonb),
                        :basis_version,
                        now()
                    )
                """),
                [
                    {
                        "genre_id": row.genre_id,
                        "color_hex": row.color_hex,
                        "confidence": row.confidence,
                        "root_affinity": json.dumps(row.root_affinity, sort_keys=True),
                        "basis_version": BASIS_VERSION,
                    }
                    for row in color_rows
                ],
            )

        await conn.execute(
            text("""
                INSERT INTO wg_snapshots (
                    id, kind, started_at, finished_at, nodes_total, edges_total, notes
                )
                SELECT
                    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                        || '-genre-colors',
                    'reconciler',
                    now(),
                    now(),
                    :nodes_total,
                    :edges_total,
                    :notes
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "nodes_total": stats.colored_genres,
                "edges_total": stats.edges_scanned,
                "notes": ("Root-affinity OKLab color index for graph-similarity genre coloring."),
            },
        )

    logger.info(
        "genre_colors_complete",
        total_genres=stats.total_genres,
        colored_genres=stats.colored_genres,
        edges_scanned=stats.edges_scanned,
        deleted_existing=stats.deleted_existing,
    )
    return stats
