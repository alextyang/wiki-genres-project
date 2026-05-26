"""Materialize Music-root reachability for display parents.

The explorer uses a synthetic "Music" root. This index records every active
display parent edge whose parent can be reached from that root, plus the
parent's depth from Music and a canonical path to reveal.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations
from wiki_genres.loader.cycle_guard import DEFAULT_ROOT_TITLES, DISPLAY_RELATIONS, RELATED_RELATION

logger = structlog.get_logger(__name__)

MUSIC_ROOT_ID = "__music_root__"
MUSIC_ROOT_RELATION = "music_root"
MUSIC_ROOT_SOURCE = "music_root"
MUSIC_COUNTRY_ROOT_SOURCE = "music_country_root"
SUPPLEMENTAL_MUSIC_ROOT_SOURCE = "supplemental_music_root"
ORIGIN_PARENT_RELATION = "origin_parent"
ORIGIN_PARENT_EVIDENCE_RELATIONS = ("stylistic_origin_of",)
HISTORICAL_ROOT_TITLES = (
    "Ancient music",
    "Prehistoric music",
    "Early music",
    "Medieval music",
    "Renaissance music",
    "Baroque music",
    "Classical period (music)",
    "Romantic music",
)


@dataclass(frozen=True)
class RootGenre:
    genre_id: str
    title: str
    ordinal: int
    source: str = MUSIC_ROOT_SOURCE


@dataclass(frozen=True)
class ReachabilityEdge:
    from_genre_id: str
    to_genre_id: str
    relation: str
    source: str
    ordinal: int
    from_title: str
    to_title: str
    evidence_relation: str | None = None

    @property
    def effective_relation(self) -> str:
        if self.relation == RELATED_RELATION and self.evidence_relation in DISPLAY_RELATIONS:
            return self.evidence_relation
        if (
            self.relation == RELATED_RELATION
            and self.evidence_relation in ORIGIN_PARENT_EVIDENCE_RELATIONS
        ):
            return ORIGIN_PARENT_RELATION
        return self.relation


@dataclass(frozen=True)
class ReachableState:
    genre_id: str
    title: str
    root_genre_id: str
    root_title: str
    depth_from_music: int
    path_genre_ids: tuple[str, ...]
    path_titles: tuple[str, ...]


@dataclass(frozen=True)
class ReachableParent:
    genre_id: str
    title: str
    parent_genre_id: str
    parent_title: str
    root_genre_id: str
    root_title: str
    parent_relation: str
    parent_source: str
    parent_ordinal: int
    parent_depth_from_music: int
    depth_from_music: int
    path_genre_ids: tuple[str, ...]
    path_titles: tuple[str, ...]


@dataclass(frozen=True)
class OrphanGenre:
    genre_id: str
    title: str
    monthly_views_p30: int | None = None


@dataclass
class MusicReachabilityStats:
    roots_requested: int = 0
    roots_found: int = 0
    roots_missing: list[str] = field(default_factory=list)
    music_country_roots_found: int = 0
    total_genres: int = 0
    edges_scanned: int = 0
    reachable_nodes: int = 0
    orphaned_nodes: int = 0
    indexed_parent_edges: int = 0
    deleted_existing: int = 0
    skipped_cycle_edges: int = 0
    skipped_depth_limited_edges: int = 0
    dry_run: bool = False
    sample: list[ReachableParent] = field(default_factory=list)
    orphan_sample: list[OrphanGenre] = field(default_factory=list)


def _build_adjacency(edges: list[ReachabilityEdge]) -> dict[str, list[ReachabilityEdge]]:
    adjacency: dict[str, list[ReachabilityEdge]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.from_genre_id].append(edge)
    return dict(adjacency)


def _is_better_state(candidate: ReachableState, existing: ReachableState | None) -> bool:
    if existing is None:
        return True
    return (
        candidate.depth_from_music,
        candidate.root_title.lower(),
        candidate.title.lower(),
        candidate.path_titles,
    ) < (
        existing.depth_from_music,
        existing.root_title.lower(),
        existing.title.lower(),
        existing.path_titles,
    )


def compute_reachable_parents(
    roots: list[RootGenre],
    edges: list[ReachabilityEdge],
    *,
    max_depth: int = 16,
    sample_size: int = 25,
) -> tuple[dict[str, ReachableState], list[ReachableParent], int, int, list[ReachableParent]]:
    """Return canonical node states and all parent edges reachable from Music.

    Node reachability uses the shortest canonical path. Parent-edge rows are
    broader: every active display edge is indexed when its parent is reachable.
    That gives the UI all alternate parents without requiring every alternate
    full path to be enumerated.
    """
    adjacency = _build_adjacency(edges)
    reachable: dict[str, ReachableState] = {}
    queue: deque[ReachableState] = deque()

    for root in roots:
        state = ReachableState(
            genre_id=root.genre_id,
            title=root.title,
            root_genre_id=root.genre_id,
            root_title=root.title,
            depth_from_music=1,
            path_genre_ids=(root.genre_id,),
            path_titles=(root.title,),
        )
        if _is_better_state(state, reachable.get(root.genre_id)):
            reachable[root.genre_id] = state
            queue.append(state)

    skipped_cycle_edges = 0
    skipped_depth_limited_edges = 0

    while queue:
        state = queue.popleft()
        if reachable.get(state.genre_id) is not state:
            continue
        if state.depth_from_music >= max_depth:
            skipped_depth_limited_edges += len(adjacency.get(state.genre_id, ()))
            continue

        for edge in adjacency.get(state.genre_id, ()):
            if edge.to_genre_id in state.path_genre_ids:
                skipped_cycle_edges += 1
                continue
            candidate = ReachableState(
                genre_id=edge.to_genre_id,
                title=edge.to_title,
                root_genre_id=state.root_genre_id,
                root_title=state.root_title,
                depth_from_music=state.depth_from_music + 1,
                path_genre_ids=state.path_genre_ids + (edge.to_genre_id,),
                path_titles=state.path_titles + (edge.to_title,),
            )
            if _is_better_state(candidate, reachable.get(edge.to_genre_id)):
                reachable[edge.to_genre_id] = candidate
                queue.append(candidate)

    parent_rows: list[ReachableParent] = []

    for root in roots:
        root_state = reachable.get(root.genre_id)
        if not root_state:
            continue
        parent_rows.append(
            ReachableParent(
                genre_id=root.genre_id,
                title=root.title,
                parent_genre_id=MUSIC_ROOT_ID,
                parent_title="Music",
                root_genre_id=root.genre_id,
                root_title=root.title,
                parent_relation=MUSIC_ROOT_RELATION,
                parent_source=root.source,
                parent_ordinal=root.ordinal,
                parent_depth_from_music=0,
                depth_from_music=1,
                path_genre_ids=root_state.path_genre_ids,
                path_titles=root_state.path_titles,
            )
        )

    seen_parent_keys = {
        (
            row.genre_id,
            row.parent_genre_id,
            row.parent_relation,
            row.parent_source,
            row.parent_ordinal,
        )
        for row in parent_rows
    }

    for edge in edges:
        parent_state = reachable.get(edge.from_genre_id)
        if not parent_state:
            continue
        if parent_state.depth_from_music >= max_depth:
            skipped_depth_limited_edges += 1
            continue
        if edge.to_genre_id in parent_state.path_genre_ids:
            skipped_cycle_edges += 1
            continue
        key = (
            edge.to_genre_id,
            edge.from_genre_id,
            edge.effective_relation,
            edge.source,
            edge.ordinal,
        )
        if key in seen_parent_keys:
            continue
        seen_parent_keys.add(key)
        parent_rows.append(
            ReachableParent(
                genre_id=edge.to_genre_id,
                title=edge.to_title,
                parent_genre_id=edge.from_genre_id,
                parent_title=edge.from_title,
                root_genre_id=parent_state.root_genre_id,
                root_title=parent_state.root_title,
                parent_relation=edge.effective_relation,
                parent_source=edge.source,
                parent_ordinal=edge.ordinal,
                parent_depth_from_music=parent_state.depth_from_music,
                depth_from_music=parent_state.depth_from_music + 1,
                path_genre_ids=parent_state.path_genre_ids + (edge.to_genre_id,),
                path_titles=parent_state.path_titles + (edge.to_title,),
            )
        )

    parent_rows.sort(
        key=lambda row: (
            row.depth_from_music,
            row.title.lower(),
            row.parent_depth_from_music,
            row.parent_title.lower(),
            row.parent_relation,
            row.parent_source,
            row.parent_ordinal,
        )
    )
    return (
        reachable,
        parent_rows,
        skipped_cycle_edges,
        skipped_depth_limited_edges,
        parent_rows[:sample_size],
    )


def compute_orphan_genres(
    genres: list[OrphanGenre],
    reachable: dict[str, ReachableState],
    *,
    sample_size: int = 25,
) -> tuple[int, list[OrphanGenre]]:
    """Return count and high-pageview sample of active genres not reachable from Music."""
    orphaned = [genre for genre in genres if genre.genre_id not in reachable]
    orphaned.sort(
        key=lambda genre: (
            -(genre.monthly_views_p30 or 0),
            genre.title.lower(),
        )
    )
    return len(orphaned), orphaned[:sample_size]


async def _resolve_root_ids(
    conn: object,
    root_titles: tuple[str, ...],
) -> tuple[list[RootGenre], list[str]]:
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

    roots: list[RootGenre] = []
    missing: list[str] = []
    for ordinal, title in enumerate(root_titles):
        root_id = id_by_title.get(title)
        if root_id:
            roots.append(RootGenre(root_id, title, ordinal))
        else:
            missing.append(title)
    return roots, missing


async def _resolve_music_country_roots(
    conn: object,
    *,
    ordinal_offset: int,
    exclude_ids: set[str],
) -> list[RootGenre]:
    rows = (
        (
            await conn.execute(  # type: ignore[attr-defined]
                text("""
            SELECT id, wikipedia_title
            FROM wg_genres
            WHERE (
                id IN (
                    SELECT p.genre_id
                    FROM wg_region_promoted_genres p
                    JOIN wg_regions r ON r.id = p.region_id
                    WHERE r.kind = 'country'
                )
                OR (
                    id NOT IN (SELECT genre_id FROM wg_region_promoted_genres)
                    AND (
                        wikipedia_title ILIKE 'Traditional music of %'
                        OR wikipedia_title ILIKE 'Traditional % music'
                        OR wikipedia_title ILIKE '% traditional music'
                        OR wikipedia_title ILIKE 'Indigenous music%'
                        OR wikipedia_title ILIKE 'Indigenous % music'
                        OR wikipedia_title ILIKE 'Ancient % music'
                        OR wikipedia_title ILIKE 'Music in ancient %'
                        OR wikipedia_title ILIKE 'Music of ancient %'
                        OR wikipedia_title = ANY(:historical_titles)
                    )
                )
            )
              AND deleted_at IS NULL
              AND is_non_genre = false
              AND id <> ALL(:exclude_ids)
            ORDER BY wikipedia_title
        """),
                {
                    "exclude_ids": list(exclude_ids),
                    "historical_titles": list(HISTORICAL_ROOT_TITLES),
                },
            )
        )
        .mappings()
        .fetchall()
    )
    return [
        RootGenre(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            ordinal=ordinal_offset + index,
            source=(
                MUSIC_COUNTRY_ROOT_SOURCE
                if row["wikipedia_title"].lower().startswith("music of ")
                else SUPPLEMENTAL_MUSIC_ROOT_SOURCE
            ),
        )
        for index, row in enumerate(rows)
    ]


async def index_music_reachability(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
    max_depth: int = 16,
    root_titles: tuple[str, ...] = DEFAULT_ROOT_TITLES,
) -> MusicReachabilityStats:
    """Rebuild ``wg_music_reachable_parents`` from active display edges."""
    await apply_migrations()
    engine = get_engine()
    stats = MusicReachabilityStats(
        roots_requested=len(root_titles),
        dry_run=dry_run,
    )

    async with engine.connect() as conn:
        roots, missing = await _resolve_root_ids(conn, root_titles)
        hidden_roots = await _resolve_music_country_roots(
            conn,
            ordinal_offset=len(root_titles),
            exclude_ids={root.genre_id for root in roots},
        )
        roots = [*roots, *hidden_roots]
        stats.roots_found = len(roots)
        stats.roots_missing = missing
        stats.music_country_roots_found = len(hidden_roots)

        relation_order = {
            **{relation: i for i, relation in enumerate(DISPLAY_RELATIONS)},
            ORIGIN_PARENT_RELATION: len(DISPLAY_RELATIONS),
        }
        rows = (
            (
                await conn.execute(
                    text("""
                SELECT
                    e.from_genre_id,
                    e.to_genre_id,
                    e.relation,
                    e.evidence_relation,
                    e.source,
                    e.ordinal,
                    from_g.wikipedia_title AS from_title,
                    to_g.wikipedia_title AS to_title
                FROM wg_edges e
                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                WHERE e.to_genre_id IS NOT NULL
                  AND (
                    e.relation = ANY(:relations)
                    OR (
                      e.relation = :related_relation
                      AND e.evidence_relation = ANY(:relations)
                    )
                    OR (
                      e.relation = :related_relation
                      AND e.evidence_relation = ANY(:origin_parent_evidence_relations)
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
                        "related_relation": RELATED_RELATION,
                        "origin_parent_evidence_relations": list(ORIGIN_PARENT_EVIDENCE_RELATIONS),
                    },
                )
            )
            .mappings()
            .fetchall()
        )

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

    edges = [
        ReachabilityEdge(
            from_genre_id=row["from_genre_id"],
            to_genre_id=row["to_genre_id"],
            relation=row["relation"],
            source=row["source"],
            ordinal=row["ordinal"],
            from_title=row["from_title"],
            to_title=row["to_title"],
            evidence_relation=row["evidence_relation"],
        )
        for row in rows
    ]
    edges.sort(
        key=lambda edge: (
            edge.from_title.lower(),
            relation_order.get(edge.effective_relation, 99),
            edge.to_title.lower(),
            edge.source,
            edge.ordinal,
        )
    )
    stats.edges_scanned = len(edges)
    genres = [
        OrphanGenre(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            monthly_views_p30=row["monthly_views_p30"],
        )
        for row in genre_rows
    ]
    stats.total_genres = len(genres)

    reachable, parent_rows, skipped_cycle, skipped_depth, sample = compute_reachable_parents(
        roots,
        edges,
        max_depth=max_depth,
        sample_size=sample_size,
    )
    orphaned_nodes, orphan_sample = compute_orphan_genres(
        genres,
        reachable,
        sample_size=sample_size,
    )
    stats.reachable_nodes = len(reachable)
    stats.orphaned_nodes = orphaned_nodes
    stats.indexed_parent_edges = len(parent_rows)
    stats.skipped_cycle_edges = skipped_cycle
    stats.skipped_depth_limited_edges = skipped_depth
    stats.sample = sample
    stats.orphan_sample = orphan_sample

    if dry_run:
        logger.info(
            "music_reachability_dry_run",
            total_genres=stats.total_genres,
            reachable_nodes=stats.reachable_nodes,
            orphaned_nodes=stats.orphaned_nodes,
            indexed_parent_edges=stats.indexed_parent_edges,
        )
        return stats

    async with engine.begin() as conn:
        deleted = await conn.execute(text("DELETE FROM wg_music_reachable_parents"))
        stats.deleted_existing = int(deleted.rowcount or 0)

        if parent_rows:
            await conn.execute(
                text("""
                    INSERT INTO wg_music_reachable_parents (
                        genre_id,
                        parent_genre_id,
                        root_genre_id,
                        parent_relation,
                        parent_source,
                        parent_ordinal,
                        parent_depth_from_music,
                        depth_from_music,
                        path_genre_ids,
                        indexed_at
                    )
                    VALUES (
                        :genre_id,
                        :parent_genre_id,
                        :root_genre_id,
                        :parent_relation,
                        :parent_source,
                        :parent_ordinal,
                        :parent_depth_from_music,
                        :depth_from_music,
                        :path_genre_ids,
                        now()
                    )
                """),
                [
                    {
                        "genre_id": row.genre_id,
                        "parent_genre_id": row.parent_genre_id,
                        "root_genre_id": row.root_genre_id,
                        "parent_relation": row.parent_relation,
                        "parent_source": row.parent_source,
                        "parent_ordinal": row.parent_ordinal,
                        "parent_depth_from_music": row.parent_depth_from_music,
                        "depth_from_music": row.depth_from_music,
                        "path_genre_ids": list(row.path_genre_ids),
                    }
                    for row in parent_rows
                ],
            )

        await conn.execute(
            text("""
                INSERT INTO wg_snapshots (
                    id, kind, started_at, finished_at, nodes_total, edges_total, notes
                )
                SELECT
                    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                        || '-music-reachability',
                    'reconciler',
                    now(),
                    now(),
                    :nodes_total,
                    :edges_total,
                    :notes
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "nodes_total": stats.reachable_nodes,
                "edges_total": stats.indexed_parent_edges,
                "notes": (
                    "Music-root reachability index for graph-visible parents "
                    "with depth and canonical reveal paths."
                ),
            },
        )

    logger.info(
        "music_reachability_complete",
        total_genres=stats.total_genres,
        reachable_nodes=stats.reachable_nodes,
        orphaned_nodes=stats.orphaned_nodes,
        indexed_parent_edges=stats.indexed_parent_edges,
        deleted_existing=stats.deleted_existing,
    )
    return stats
