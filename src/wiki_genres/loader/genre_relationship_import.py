"""Import GPT-reviewed genre relationships into the canonical schema."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

RELATIONSHIP_TYPES = (
    "broader_genres",
    "subgenres",
    "source_genres",
    "derived_genres",
    "fusion_components",
    "fusion_descendants",
    "regional_variations",
    "sibling_or_adjacent_genres",
    "influenced_by",
    "influences",
)


@dataclass
class GenreRelationshipImportStats:
    rows_read: int = 0
    relationships_inserted: int = 0
    missing_targets_inserted: int = 0
    skipped_self_relationships: int = 0
    skipped_missing_source_genres: int = 0
    deleted_existing_relationships: int = 0
    deleted_existing_missing_targets: int = 0


def _loads_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _title_key(title: str | None) -> str:
    return (title or "").strip().casefold()


async def import_reviewed_genre_relationships(
    csv_path: Path,
    *,
    review_run_id: str,
    replace_review_run: bool = True,
) -> GenreRelationshipImportStats:
    """Load normalized relationship-review CSV output into canonical tables."""
    await apply_migrations()
    stats = GenreRelationshipImportStats()
    engine = get_engine()

    csv.field_size_limit(sys.maxsize)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    stats.rows_read = len(rows)

    async with engine.begin() as conn:
        title_rows = (
            (
                await conn.execute(
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
        id_by_title = {_title_key(row["wikipedia_title"]): row["id"] for row in title_rows}
        title_by_id = {row["id"]: row["wikipedia_title"] for row in title_rows}

        if replace_review_run:
            result = await conn.execute(
                text("""
                    DELETE FROM wg_genre_relationships
                    WHERE review_run_id = :review_run_id
                """),
                {"review_run_id": review_run_id},
            )
            stats.deleted_existing_relationships = int(result.rowcount or 0)
            result = await conn.execute(
                text("""
                    DELETE FROM wg_missing_genre_relationship_targets
                    WHERE review_run_id = :review_run_id
                """),
                {"review_run_id": review_run_id},
            )
            stats.deleted_existing_missing_targets = int(result.rowcount or 0)

        for row in rows:
            from_genre_id = (row.get("genre_id") or "").strip()
            if not from_genre_id or from_genre_id not in title_by_id:
                stats.skipped_missing_source_genres += 1
                continue

            relationships = _loads_json(row.get("new_relationships_json")) or {}
            ordinal = 0
            for relationship_type in RELATIONSHIP_TYPES:
                items = relationships.get(relationship_type) or []
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    target_title = (item.get("title") or "").strip()
                    target_id = id_by_title.get(_title_key(target_title))
                    if not target_id:
                        await conn.execute(
                            text("""
                                INSERT INTO wg_missing_genre_relationship_targets (
                                    from_genre_id,
                                    target_label,
                                    relationship_type,
                                    target_action,
                                    confidence,
                                    evidence,
                                    justification,
                                    review_run_id,
                                    status
                                )
                                VALUES (
                                    :from_genre_id,
                                    :target_label,
                                    :relationship_type,
                                    :target_action,
                                    :confidence,
                                    :evidence,
                                    :justification,
                                    :review_run_id,
                                    'pending'
                                )
                            """),
                            {
                                "from_genre_id": from_genre_id,
                                "target_label": target_title,
                                "relationship_type": relationship_type,
                                "target_action": "map_to_existing_node_needed",
                                "confidence": item.get("confidence"),
                                "evidence": item.get("evidence"),
                                "justification": item.get("justification"),
                                "review_run_id": review_run_id,
                            },
                        )
                        stats.missing_targets_inserted += 1
                        continue
                    if target_id == from_genre_id:
                        stats.skipped_self_relationships += 1
                        continue
                    await conn.execute(
                        text("""
                            INSERT INTO wg_genre_relationships (
                                from_genre_id,
                                to_genre_id,
                                to_raw_label,
                                relationship_type,
                                source,
                                ordinal,
                                confidence,
                                evidence,
                                justification,
                                review_run_id,
                                status
                            )
                            VALUES (
                                :from_genre_id,
                                :to_genre_id,
                                :to_raw_label,
                                :relationship_type,
                                'gpt_review',
                                :ordinal,
                                :confidence,
                                :evidence,
                                :justification,
                                :review_run_id,
                                'active'
                            )
                        """),
                        {
                            "from_genre_id": from_genre_id,
                            "to_genre_id": target_id,
                            "to_raw_label": target_title or title_by_id[target_id],
                            "relationship_type": relationship_type,
                            "ordinal": ordinal,
                            "confidence": item.get("confidence"),
                            "evidence": item.get("evidence"),
                            "justification": item.get("justification"),
                            "review_run_id": review_run_id,
                        },
                    )
                    stats.relationships_inserted += 1
                    ordinal += 1

            missing_targets = _loads_json(row.get("missing_target_relationships_json")) or []
            if isinstance(missing_targets, list):
                for item in missing_targets:
                    if not isinstance(item, dict):
                        continue
                    relationship_type = item.get("relationship_type")
                    if relationship_type not in RELATIONSHIP_TYPES:
                        continue
                    await conn.execute(
                        text("""
                            INSERT INTO wg_missing_genre_relationship_targets (
                                from_genre_id,
                                target_label,
                                relationship_type,
                                target_action,
                                confidence,
                                evidence,
                                justification,
                                review_run_id,
                                status
                            )
                            VALUES (
                                :from_genre_id,
                                :target_label,
                                :relationship_type,
                                :target_action,
                                :confidence,
                                :evidence,
                                :justification,
                                :review_run_id,
                                'pending'
                            )
                        """),
                        {
                            "from_genre_id": from_genre_id,
                            "target_label": item.get("title"),
                            "relationship_type": relationship_type,
                            "target_action": item.get("target_entity_action"),
                            "confidence": item.get("confidence"),
                            "evidence": item.get("evidence"),
                            "justification": item.get("justification"),
                            "review_run_id": review_run_id,
                        },
                    )
                    stats.missing_targets_inserted += 1

    return stats
