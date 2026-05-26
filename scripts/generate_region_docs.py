from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations


GENERATED_DIR = Path("docs/generated")
STYLE_RELATIONS = {"regional_style_mention", "influence_or_context"}
REMOVED_STATUSES = {"collapsed", "rejected", "demoted_source", "hidden_from_ui"}


def _status(row: dict[str, Any]) -> str:
    return str(row.get("production_status") or "")


def _visibility(row: dict[str, Any]) -> str:
    return str(row.get("ui_visibility") or "")


def _is_removed(row: dict[str, Any]) -> bool:
    return _status(row) in REMOVED_STATUSES or _visibility(row) in REMOVED_STATUSES


def _line_for_region(
    *,
    region: dict[str, Any],
    relations: list[str],
    repeated: bool,
    depth: int,
) -> str:
    sign = "-" if _is_removed(region) else "+"
    pieces = [str(region.get("kind") or "unknown")]
    if _status(region):
        pieces.append(_status(region))
    if _visibility(region):
        pieces.append(_visibility(region))
    if relations:
        pieces.append(f"relations: {', '.join(relations)}")
    if repeated:
        pieces.append("also listed elsewhere")
    pieces.append(f"owned genres: {int(region.get('owned_genres') or 0)}")
    pieces.append(f"inferred candidates: {int(region.get('inferred_candidates') or 0)}")
    title = region.get("wikipedia_title")
    if title:
        pieces.append(str(title))
    return f"{'  ' * depth}{sign} {region['canonical_name']} ({'; '.join(pieces)})"


async def _load_region_rows(conn) -> dict[str, dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    WITH owned AS (
                        SELECT region_id, count(DISTINCT genre_id) AS count
                        FROM wg_region_genre_relationships
                        WHERE status = 'accepted'
                          AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                        GROUP BY region_id
                    ),
                    inferred AS (
                        SELECT region_id, count(DISTINCT proposed_display_title) AS count
                        FROM wg_region_inferred_genres
                        WHERE status <> 'rejected'
                        GROUP BY region_id
                    )
                    SELECT
                        r.id,
                        r.canonical_name,
                        r.kind,
                        r.wikipedia_title,
                        coalesce(r.raw_payload #>> '{region_production_review,status}', '') AS production_status,
                        coalesce(r.raw_payload #>> '{region_accessibility,ui_visibility}', '') AS ui_visibility,
                        coalesce(r.raw_payload #>> '{region_accessibility,special_map}', '') AS special_map,
                        (p.region_id IS NOT NULL) AS promoted,
                        coalesce(owned.count, 0) AS owned_genres,
                        coalesce(inferred.count, 0) AS inferred_candidates
                    FROM wg_regions r
                    LEFT JOIN wg_region_promoted_genres p ON p.region_id = r.id
                    LEFT JOIN owned ON owned.region_id = r.id
                    LEFT JOIN inferred ON inferred.region_id = r.id
                    ORDER BY r.canonical_name
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    return {str(row["id"]): dict(row) for row in rows}


async def _load_relationship_rows(conn) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT from_region_id, to_region_id, relation, status
                    FROM wg_region_relationships
                    ORDER BY to_region_id, from_region_id, relation
                """)
            )
        )
        .mappings()
        .fetchall()
    )
    return [dict(row) for row in rows]


def _build_relationship_indexes(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, list[str]],
    dict[tuple[str, str], set[str]],
    set[str],
    dict[str, list[str]],
    dict[tuple[str, str], set[str]],
]:
    accepted_children: dict[str, list[str]] = defaultdict(list)
    accepted_relations: dict[tuple[str, str], set[str]] = defaultdict(set)
    rejected_children: dict[str, list[str]] = defaultdict(list)
    rejected_relations: dict[tuple[str, str], set[str]] = defaultdict(set)
    accepted_child_ids: set[str] = set()

    for row in rows:
        child = str(row["from_region_id"])
        parent = str(row["to_region_id"])
        relation = str(row["relation"])
        if row["status"] == "accepted":
            accepted_children[parent].append(child)
            accepted_relations[(parent, child)].add(relation)
            accepted_child_ids.add(child)
        elif row["status"] == "rejected":
            rejected_children[parent].append(child)
            rejected_relations[(parent, child)].add(relation)

    for child_list in [*accepted_children.values(), *rejected_children.values()]:
        child_list.sort()

    return (
        accepted_children,
        accepted_relations,
        accepted_child_ids,
        rejected_children,
        rejected_relations,
    )


def _render_tree(
    regions: dict[str, dict[str, Any]],
    rel_rows: list[dict[str, Any]],
) -> str:
    (
        accepted_children,
        accepted_relations,
        accepted_child_ids,
        rejected_children,
        rejected_relations,
    ) = _build_relationship_indexes(rel_rows)

    root_ids = [
        region_id
        for region_id, row in regions.items()
        if region_id not in accepted_child_ids
        and not _is_removed(row)
        and (row.get("promoted") or row.get("kind") in {"continent", "superregion"})
    ]
    root_ids.sort(key=lambda rid: str(regions[rid]["canonical_name"]))

    seen: set[str] = set()
    lines: list[str] = []

    def walk(region_id: str, depth: int, relations: list[str]) -> None:
        region = regions.get(region_id)
        if not region:
            return
        repeated = region_id in seen
        lines.append(
            _line_for_region(
                region=region,
                relations=relations,
                repeated=repeated,
                depth=depth,
            )
        )
        if repeated:
            return
        seen.add(region_id)

        children = sorted(
            set(accepted_children.get(region_id, [])) | set(rejected_children.get(region_id, [])),
            key=lambda child_id: str(regions.get(child_id, {}).get("canonical_name", child_id)),
        )
        for child_id in children:
            child_relations = sorted(
                accepted_relations.get((region_id, child_id), set())
                | rejected_relations.get((region_id, child_id), set())
            )
            walk(child_id, depth + 1, child_relations)

    for root_id in root_ids:
        walk(root_id, 0, [])

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    removed_count = sum(1 for row in regions.values() if _is_removed(row))
    accepted_links = sum(1 for row in rel_rows if row["status"] == "accepted")
    rejected_links = sum(1 for row in rel_rows if row["status"] == "rejected")
    promoted = sum(1 for row in regions.values() if row.get("promoted"))
    body = "\n".join(lines)
    return f"""# Regional Relation Tree

Generated: {generated}

Legend:
`+` retained/current region or relationship.
`-` removed or hidden by the hierarchy/accessibility pass.
Genre counts are unique accepted graph genres; inferred counts are unique non-rejected inferred candidates.
Repeated regions are listed under every accepted parent and marked `also listed elsewhere` on repeated traversal.

Summary:
`Regions`: {len(regions)}
`Promoted regions`: {promoted}
`Removed/hidden regions`: {removed_count}
`Accepted parent relationship rows represented`: {accepted_links}
`Rejected parent relationship rows represented`: {rejected_links}

## Current Accepted Tree

{body}
"""


def _render_special_map_inventory(
    regions: dict[str, dict[str, Any]],
    rel_rows: list[dict[str, Any]],
) -> str:
    accepted_parent_by_child: dict[str, set[str]] = defaultdict(set)
    active_child_regions_by_parent: dict[str, int] = defaultdict(int)
    for row in rel_rows:
        if row["status"] != "accepted":
            continue
        child = str(row["from_region_id"])
        parent = str(row["to_region_id"])
        accepted_parent_by_child[child].add(parent)
        if not _is_removed(regions.get(child, {})):
            active_child_regions_by_parent[parent] += 1

    map_children: dict[str, list[str]] = defaultdict(list)
    for child_id, row in regions.items():
        if not row.get("special_map"):
            continue
        for parent_id in accepted_parent_by_child.get(child_id, set()):
            if regions.get(parent_id, {}).get("kind") == "country":
                map_children[parent_id].append(child_id)

    table_rows: list[str] = []
    detail_lines: list[str] = []
    for country_id in sorted(map_children, key=lambda rid: str(regions[rid]["canonical_name"])):
        children = sorted(
            map_children[country_id],
            key=lambda rid: str(regions[rid]["canonical_name"]),
        )
        visible = [child_id for child_id in children if not _is_removed(regions[child_id])]
        collapsed = len(children) - len(visible)
        country = regions[country_id]
        table_rows.append(
            f"| {country['canonical_name']} | {len(children)} | {len(visible)} | {collapsed} |"
        )
        detail_lines.append(f"### {country['canonical_name']}")
        for child_id in children:
            child = regions[child_id]
            sign = "-" if _is_removed(child) else "+"
            detail_lines.append(
                f"{sign} {child['canonical_name']} ({child['kind']}; "
                f"{_visibility(child) or 'special_country_subregion'}; "
                f"owned genres: {int(child.get('owned_genres') or 0)}; "
                f"inferred candidates: {int(child.get('inferred_candidates') or 0)}; "
                f"active child regions: {active_child_regions_by_parent.get(child_id, 0)}; "
                f"{child.get('wikipedia_title') or ''})"
            )
        detail_lines.append("")

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    table = "\n".join(table_rows) if table_rows else "| _None._ | 0 | 0 | 0 |"
    details = "\n".join(detail_lines).strip() or "_None._"
    return f"""# Special Region Map Inventory

Generated: {generated}

This inventory counts configured special-map country children. City rows and collapsed rows are excluded from visible counts.

## Implemented Special Maps

| Country | map-eligible children with signal | currently visible as special-map children | collapsed/hidden signal rows |
| --- | ---: | ---: | ---: |
{table}

## Implemented Map Children

{details}
"""


async def main() -> None:
    await apply_migrations()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    async with engine.connect() as conn:
        regions = await _load_region_rows(conn)
        rel_rows = await _load_relationship_rows(conn)

    (GENERATED_DIR / "REGIONAL_RELATION_TREE.md").write_text(
        _render_tree(regions, rel_rows),
        encoding="utf-8",
    )
    (GENERATED_DIR / "SPECIAL_REGION_MAP_INVENTORY.md").write_text(
        _render_special_map_inventory(regions, rel_rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
