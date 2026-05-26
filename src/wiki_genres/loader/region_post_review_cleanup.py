"""Deterministic cleanup for remaining regional graph review findings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

CLEANUP_MODEL = "deterministic-region-post-review-cleanup-v1"
GRAPH_NON_PROMOTED_RELATIONS = ("regional_style_mention", "influence_or_context")


@dataclass
class RegionPostReviewCleanupStats:
    dry_run: bool = False
    region_status_updates: int = 0
    region_kind_updates: int = 0
    region_title_updates: int = 0
    parent_edges_rejected: int = 0
    region_genre_edges_rejected: int = 0
    city_genre_edges_accepted: int = 0
    collapsed_display_edges_rejected: int = 0
    stale_city_visibility_updates: int = 0
    duplicate_region_edges_rejected: int = 0
    duplicate_region_genre_edges_rejected: int = 0
    hierarchy_edges_added: int = 0
    inferred_variants_resolved: int = 0
    inferred_variant_edges_added: int = 0
    fuzzy_base_equivalent_variants_resolved: int = 0
    sample: list[str] = field(default_factory=list)


async def apply_region_post_review_cleanup(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
) -> RegionPostReviewCleanupStats:
    """Apply high-confidence deterministic fixes from the full-region review."""
    await apply_migrations()
    stats = RegionPostReviewCleanupStats(dry_run=dry_run)

    rejected_region_ids = [
        "region-national-centre-of-excellence-in",
        "region-insular-areas-of-the-united-states",
    ]
    collapsed_region_ids = [
        "region-movement-against-apartheid",
        "region-transylvania",
        "region-irish",
        "region-slovak",
        "region-kosovan",
        "region-soviet-union",
    ]
    demote_source_region_ids = ["region-latin"]
    kind_updates = {
        "region-timor-leste": "country",
        "region-southern-united-states": "cultural_region",
        "region-san-francisco-bay-area": "subregion",
        "region-crete": "subregion",
        "region-bali": "subregion",
        "region-english": "cultural_region",
        "region-kurdish": "cultural_region",
        "region-manila": "city",
        "region-tucson-arizona": "city",
    }
    title_updates = {
        "region-celtic": "Celtic music",
        "region-western-australia": "Music of Western Australia",
        "region-dutch-west-indies": "Music of Dutch West Indies",
        "region-stirling-council-area": "Music of Stirling",
    }
    bad_parent_edges = [
        ("region-samoa", "region-united-states"),
        ("region-samoa", "region-american-samoa"),
        ("region-comoros", "region-france"),
        ("region-comoros", "region-mayotte"),
        ("region-monaco", "region-france"),
        ("region-cook-islands", "region-new-zealand"),
        ("region-isle-of-man", "region-united-kingdom"),
        ("region-saint-helena", "region-united-kingdom"),
        ("region-tahiti", "region-france"),
        ("region-french-polynesia", "region-france"),
        ("region-kiribati", "region-micronesia"),
        ("region-marshall-islands", "region-micronesia"),
        ("region-virgin-islands", "region-united-kingdom"),
        ("region-virgin-islands", "region-united-states"),
        ("region-virgin-islands", "region-insular-areas-of-the-united-states"),
        ("region-virgin-islands", "region-british-virgin-islands"),
        ("region-american-samoa", "region-insular-areas-of-the-united-states"),
        ("region-guam", "region-insular-areas-of-the-united-states"),
        ("region-northern-mariana-islands", "region-insular-areas-of-the-united-states"),
        ("region-puerto-rico", "region-insular-areas-of-the-united-states"),
        ("region-national-centre-of-excellence-in", "region-scottish"),
        ("region-denmark", "region-switzerland"),
        ("region-finland", "region-switzerland"),
        ("region-iceland", "region-switzerland"),
        ("region-norway", "region-switzerland"),
        ("region-sweden", "region-switzerland"),
        ("region-faroe-islands", "region-switzerland"),
    ]
    required_parent_edges = [
        ("region-tahiti", "region-french-polynesia", "part_of"),
        ("region-french-polynesia", "region-polynesia", "part_of"),
        ("region-virgin-islands", "region-lesser-antilles", "part_of"),
    ]
    bad_region_genre_edges = [
        ("region-mexico", "New Mexico music"),
        ("region-united-kingdom", "Fungi (music)"),
        ("region-france", "Himene tarava"),
        ("region-new-zealand", "Imene reo metua"),
        ("region-united-kingdom", "Irish traditional music"),
    ]
    accepted_city_genre_edges = [
        ("region-vienna", "Schrammelmusik"),
        ("region-vienna", "Wienerlied"),
        ("region-genoa", "Trallalero"),
        ("region-naples", "Canzone napoletana"),
    ]
    hidden_city_ids = ["region-tucson-arizona"]

    engine = get_engine()
    async with engine.begin() as conn:
        if dry_run:
            stats.region_status_updates = int(
                await conn.scalar(
                    text("SELECT count(*) FROM wg_regions WHERE id = ANY(CAST(:ids AS text[]))"),
                    {
                        "ids": rejected_region_ids
                        + collapsed_region_ids
                        + demote_source_region_ids
                    },
                )
                or 0
            )
            stats.sample = ["dry-run: post-review cleanup would apply deterministic fixes"][
                :sample_size
            ]
            return stats

        status_result = await conn.execute(
            text("""
                UPDATE wg_regions
                SET raw_payload = jsonb_set(
                        coalesce(raw_payload, '{}'::jsonb),
                        '{region_production_review}',
                        coalesce(raw_payload #> '{region_production_review}', '{}'::jsonb)
                            || jsonb_build_object(
                                'status',
                                CASE
                                    WHEN id = ANY(CAST(:rejected_ids AS text[])) THEN 'rejected'
                                    WHEN id = ANY(CAST(:demote_source_ids AS text[])) THEN 'demoted_source'
                                    ELSE 'collapsed'
                                END,
                                'reason',
                                CASE
                                    WHEN id = ANY(CAST(:rejected_ids AS text[])) THEN 'post_review_non_region'
                                    WHEN id = ANY(CAST(:demote_source_ids AS text[])) THEN 'post_review_source_metadata_node'
                                    ELSE 'post_review_collapsed_node'
                                END,
                                'reviewer_model',
                                CAST(:reviewer_model AS text)
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE id = ANY(CAST(:ids AS text[]))
            """),
            {
                "ids": rejected_region_ids + collapsed_region_ids + demote_source_region_ids,
                "rejected_ids": rejected_region_ids,
                "demote_source_ids": demote_source_region_ids,
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.region_status_updates = int(status_result.rowcount or 0)

        kind_result = await conn.execute(
            text("""
                WITH requested(region_id, kind) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(region_id text, kind text)
                )
                UPDATE wg_regions r
                SET kind = requested.kind,
                    raw_payload = jsonb_set(
                        coalesce(r.raw_payload, '{}'::jsonb),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object('reviewer_model', CAST(:reviewer_model AS text)),
                        true
                    ),
                    updated_at = now()
                FROM requested
                WHERE requested.region_id = r.id
                  AND r.kind <> requested.kind
            """),
            {
                "values": json.dumps(
                    [{"region_id": rid, "kind": kind} for rid, kind in kind_updates.items()]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.region_kind_updates = int(kind_result.rowcount or 0)

        title_result = await conn.execute(
            text("""
                WITH requested(region_id, title) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(region_id text, title text)
                ),
                direct AS (
                    UPDATE wg_regions r
                    SET wikipedia_title = requested.title,
                        display_title = requested.title,
                        updated_at = now()
                    FROM requested
                    WHERE requested.region_id = r.id
                      AND coalesce(r.wikipedia_title, '') <> requested.title
                    RETURNING r.id
                ),
                music_in AS (
                    UPDATE wg_regions r
                    SET wikipedia_title = regexp_replace(r.wikipedia_title, '^Music in ', 'Music of '),
                        display_title = regexp_replace(
                            coalesce(r.display_title, r.wikipedia_title),
                            '^Music in ',
                            'Music of '
                        ),
                        updated_at = now()
                    WHERE r.wikipedia_title ~ '^Music in '
                    RETURNING r.id
                )
                SELECT count(*) FROM (
                    SELECT id FROM direct
                    UNION
                    SELECT id FROM music_in
                ) changed
            """),
            {
                "values": json.dumps(
                    [
                        {"region_id": rid, "title": title}
                        for rid, title in title_updates.items()
                    ]
                )
            },
        )
        stats.region_title_updates = int(title_result.scalar() or 0)

        parent_result = await conn.execute(
            text("""
                WITH requested(child_id, parent_id) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(child_id text, parent_id text)
                )
                UPDATE wg_region_relationships rel
                SET status = 'rejected',
                    review_reason = coalesce(review_reason, '') ||
                        ' Deterministic post-review cleanup rejected wrong parent routing.',
                    reviewer_model = CAST(:reviewer_model AS text),
                    updated_at = now()
                FROM requested
                WHERE rel.from_region_id = requested.child_id
                  AND rel.to_region_id = requested.parent_id
                  AND rel.status = 'accepted'
            """),
            {
                "values": json.dumps(
                    [
                        {"child_id": child_id, "parent_id": parent_id}
                        for child_id, parent_id in bad_parent_edges
                    ]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.parent_edges_rejected = int(parent_result.rowcount or 0)

        required_parent_result = await conn.execute(
            text("""
                WITH requested(child_id, parent_id, relation) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(child_id text, parent_id text, relation text)
                )
                INSERT INTO wg_region_relationships (
                    from_region_id,
                    to_region_id,
                    relation,
                    source_type,
                    source_title,
                    evidence_text,
                    confidence,
                    status,
                    review_reason,
                    reviewer_model,
                    raw_payload
                )
                SELECT
                    requested.child_id,
                    requested.parent_id,
                    requested.relation,
                    'manual',
                    'Region post-review cleanup',
                    'Required parent edge from deterministic regional graph review.',
                    0.99,
                    'accepted',
                    'Deterministic post-review cleanup added missing specific parent route.',
                    :reviewer_model,
                    jsonb_build_object('cleanup_model', CAST(:reviewer_model AS text))
                FROM requested
                WHERE EXISTS (SELECT 1 FROM wg_regions child WHERE child.id = requested.child_id)
                  AND EXISTS (SELECT 1 FROM wg_regions parent WHERE parent.id = requested.parent_id)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM wg_region_relationships existing
                    WHERE existing.from_region_id = requested.child_id
                      AND existing.to_region_id = requested.parent_id
                      AND existing.relation = requested.relation
                      AND existing.status = 'accepted'
                  )
            """),
            {
                "values": json.dumps(
                    [
                        {"child_id": child_id, "parent_id": parent_id, "relation": relation}
                        for child_id, parent_id, relation in required_parent_edges
                    ]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.hierarchy_edges_added = int(required_parent_result.rowcount or 0)

        genre_result = await conn.execute(
            text("""
                WITH requested(region_id, genre_title) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(region_id text, genre_title text)
                )
                UPDATE wg_region_genre_relationships rel
                SET status = 'rejected',
                    review_reason = coalesce(review_reason, '') ||
                        ' Deterministic post-review cleanup rejected wrong regional owner.',
                    reviewer_model = CAST(:reviewer_model AS text),
                    updated_at = now()
                FROM requested
                JOIN wg_genres genre ON lower(genre.wikipedia_title) = lower(requested.genre_title)
                WHERE rel.region_id = requested.region_id
                  AND rel.genre_id = genre.id
                  AND rel.status = 'accepted'
                  AND rel.relation not in ('regional_style_mention', 'influence_or_context')
            """),
            {
                "values": json.dumps(
                    [
                        {"region_id": region_id, "genre_title": genre_title}
                        for region_id, genre_title in bad_region_genre_edges
                    ]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.region_genre_edges_rejected = int(genre_result.rowcount or 0)

        accepted_city_genre_result = await conn.execute(
            text("""
                WITH requested(region_id, genre_title) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(region_id text, genre_title text)
                )
                UPDATE wg_region_genre_relationships rel
                SET status = 'accepted',
                    review_reason = coalesce(review_reason, '') ||
                        ' Deterministic post-review cleanup accepted named city-specific genre.',
                    reviewer_model = CAST(:reviewer_model AS text),
                    updated_at = now()
                FROM requested
                JOIN wg_genres genre ON lower(genre.wikipedia_title) = lower(requested.genre_title)
                WHERE rel.region_id = requested.region_id
                  AND rel.genre_id = genre.id
                  AND rel.status = 'rejected'
                  AND rel.relation not in ('regional_style_mention', 'influence_or_context')
            """),
            {
                "values": json.dumps(
                    [
                        {"region_id": region_id, "genre_title": genre_title}
                        for region_id, genre_title in accepted_city_genre_edges
                    ]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )
        stats.city_genre_edges_accepted = int(accepted_city_genre_result.rowcount or 0)

        await conn.execute(
            text("""
                WITH requested(region_id) AS (
                    SELECT DISTINCT region_id
                    FROM jsonb_to_recordset(CAST(:values AS jsonb))
                        AS item(region_id text, genre_title text)
                )
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(r.raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status',
                                    'approved_city_exception',
                                    'reason',
                                    'city_with_final_genres_visible',
                                    'reviewer_model',
                                    CAST(:reviewer_model AS text)
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access',
                                false,
                                'ui_visibility',
                                'country_child',
                                'reviewer_model',
                                CAST(:reviewer_model AS text)
                            ),
                        true
                    ),
                    updated_at = now()
                FROM requested
                WHERE requested.region_id = r.id
            """),
            {
                "values": json.dumps(
                    [
                        {"region_id": region_id, "genre_title": genre_title}
                        for region_id, genre_title in accepted_city_genre_edges
                    ]
                ),
                "reviewer_model": CLEANUP_MODEL,
            },
        )

        collapsed_display_result = await conn.execute(
            text("""
                UPDATE wg_region_genre_relationships rel
                SET status = 'rejected',
                    review_reason = coalesce(rel.review_reason, '') ||
                        ' Deterministic post-review cleanup suppressed display edge from hidden/collapsed region.',
                    reviewer_model = CAST(:reviewer_model AS text),
                    updated_at = now()
                FROM wg_regions region
                WHERE region.id = rel.region_id
                  AND rel.status = 'accepted'
                  AND rel.relation not in ('regional_style_mention', 'influence_or_context')
                  AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') IN (
                    'collapsed',
                    'rejected',
                    'demoted_source',
                    'hidden_from_ui'
                  )
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.collapsed_display_edges_rejected = int(collapsed_display_result.rowcount or 0)

        city_result = await conn.execute(
            text("""
                WITH visible_city AS (
                    SELECT DISTINCT r.id
                    FROM wg_regions r
                    JOIN wg_region_genre_relationships rel ON rel.region_id = r.id
                    WHERE r.kind = 'city'
                      AND rel.status = 'accepted'
                      AND rel.relation not in ('regional_style_mention', 'influence_or_context')
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') IN (
                        'hidden_from_ui',
                        'reviewed_empty',
                        'rejected'
                      )
                )
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(r.raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status',
                                    'approved_city_exception',
                                    'reason',
                                    'city_with_final_genres_visible',
                                    'reviewer_model',
                                    CAST(:reviewer_model AS text)
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access',
                                false,
                                'ui_visibility',
                                'country_child',
                                'reviewer_model',
                                CAST(:reviewer_model AS text)
                            ),
                        true
                    ),
                    updated_at = now()
                FROM visible_city
                WHERE visible_city.id = r.id
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.stale_city_visibility_updates = int(city_result.rowcount or 0)

        await conn.execute(
            text("""
                UPDATE wg_regions
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status',
                                    'hidden_from_ui',
                                    'reason',
                                    'city_without_final_genres',
                                    'reviewer_model',
                                    CAST(:reviewer_model AS text)
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access',
                                false,
                                'ui_visibility',
                                'hidden_from_ui',
                                'reviewer_model',
                                CAST(:reviewer_model AS text)
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE id = ANY(CAST(:hidden_city_ids AS text[]))
            """),
            {
                "hidden_city_ids": hidden_city_ids,
                "reviewer_model": CLEANUP_MODEL,
            },
        )

        duplicate_region_result = await conn.execute(
            text("""
                WITH ranked AS (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY from_region_id, to_region_id, relation
                            ORDER BY confidence DESC, id
                        ) AS rn
                    FROM wg_region_relationships
                    WHERE status = 'accepted'
                )
                UPDATE wg_region_relationships rel
                SET status = 'rejected',
                    review_reason = coalesce(rel.review_reason, '') ||
                        ' Deterministic post-review cleanup bundled duplicate region edge evidence.',
                    reviewer_model = :reviewer_model,
                    updated_at = now()
                FROM ranked
                WHERE ranked.id = rel.id
                  AND ranked.rn > 1
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.duplicate_region_edges_rejected = int(duplicate_region_result.rowcount or 0)

        duplicate_region_genre_result = await conn.execute(
            text("""
                WITH ranked AS (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY region_id, genre_id, relation
                            ORDER BY confidence DESC, id
                        ) AS rn
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation not in ('regional_style_mention', 'influence_or_context')
                )
                UPDATE wg_region_genre_relationships rel
                SET status = 'rejected',
                    review_reason = coalesce(rel.review_reason, '') ||
                        ' Deterministic post-review cleanup bundled duplicate region-genre evidence.',
                    reviewer_model = :reviewer_model,
                    updated_at = now()
                FROM ranked
                WHERE ranked.id = rel.id
                  AND ranked.rn > 1
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.duplicate_region_genre_edges_rejected = int(
            duplicate_region_genre_result.rowcount or 0
        )

        inferred_edge_result = await conn.execute(
            text("""
                WITH inferred_match AS (
                    SELECT DISTINCT ON (inferred.region_id, genre.id)
                        inferred.id AS inferred_id,
                        inferred.region_id,
                        inferred.base_genre_id,
                        inferred.proposed_display_title,
                        inferred.wikipedia_title,
                        inferred.source_title,
                        inferred.source_section,
                        inferred.confidence,
                        base.wikipedia_title AS base_title,
                        genre.id AS genre_id,
                        genre.wikipedia_title AS genre_title
                    FROM wg_region_inferred_genres inferred
                    JOIN wg_genres base ON base.id = inferred.base_genre_id
                    JOIN wg_genres genre
                      ON regexp_replace(
                            lower(genre.wikipedia_title),
                            '[^a-z0-9]+',
                            '',
                            'g'
                         ) = regexp_replace(
                            lower(coalesce(inferred.wikipedia_title, inferred.proposed_display_title)),
                            '[^a-z0-9]+',
                            '',
                            'g'
                         )
                     AND genre.id <> inferred.base_genre_id
                     AND genre.deleted_at IS NULL
                     AND genre.is_non_genre = false
                    JOIN wg_regions region ON region.id = inferred.region_id
                    WHERE inferred.status IN ('proposed', 'accepted')
                      AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'collapsed',
                        'rejected',
                        'demoted_source',
                        'hidden_from_ui'
                      )
                    ORDER BY inferred.region_id, genre.id, inferred.confidence DESC, inferred.id
                )
                INSERT INTO wg_region_genre_relationships (
                    region_id,
                    genre_id,
                    relation,
                    source_type,
                    source_title,
                    source_section,
                    evidence_text,
                    confidence,
                    status,
                    raw_payload,
                    review_reason,
                    reviewer_model,
                    updated_at
                )
                SELECT
                    region_id,
                    genre_id,
                    'regional_scene',
                    'manual',
                    'Regional variation candidate cleanup',
                    coalesce(source_section, source_title),
                    'Resolved inferred regional variation candidate "' ||
                        proposed_display_title || '" to existing genre "' ||
                        genre_title || '" from base genre "' || base_title || '".',
                    greatest(confidence, 0.9),
                    'accepted',
                    jsonb_build_object(
                        'cleanup_model', CAST(:reviewer_model AS text),
                        'resolved_inferred_candidate_id', inferred_id,
                        'base_genre_id', base_genre_id,
                        'base_genre_title', base_title,
                        'resolved_genre_title', genre_title
                    ),
                    'Deterministic cleanup resolved inferred regional variation to existing genre row.',
                    CAST(:reviewer_model AS text),
                    now()
                FROM inferred_match
                ON CONFLICT (
                    region_id,
                    genre_id,
                    relation,
                    source_type,
                    coalesce(source_url, ''),
                    coalesce(source_title, ''),
                    coalesce(source_section, '')
                )
                DO UPDATE
                SET status = 'accepted',
                    confidence = greatest(wg_region_genre_relationships.confidence, excluded.confidence),
                    raw_payload = wg_region_genre_relationships.raw_payload || excluded.raw_payload,
                    review_reason = excluded.review_reason,
                    reviewer_model = excluded.reviewer_model,
                    updated_at = now()
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.inferred_variant_edges_added = int(inferred_edge_result.rowcount or 0)

        inferred_status_result = await conn.execute(
            text("""
                WITH inferred_match AS (
                    SELECT
                        inferred.id AS inferred_id,
                        inferred.region_id,
                        inferred.base_genre_id,
                        inferred.proposed_display_title,
                        genre.id AS genre_id,
                        genre.wikipedia_title AS genre_title
                    FROM wg_region_inferred_genres inferred
                    JOIN wg_genres genre
                      ON regexp_replace(
                            lower(genre.wikipedia_title),
                            '[^a-z0-9]+',
                            '',
                            'g'
                         ) = regexp_replace(
                            lower(coalesce(inferred.wikipedia_title, inferred.proposed_display_title)),
                            '[^a-z0-9]+',
                            '',
                            'g'
                         )
                     AND genre.id <> inferred.base_genre_id
                     AND genre.deleted_at IS NULL
                     AND genre.is_non_genre = false
                    JOIN wg_regions region ON region.id = inferred.region_id
                    WHERE inferred.status IN ('proposed', 'accepted')
                      AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'collapsed',
                        'rejected',
                        'demoted_source',
                        'hidden_from_ui'
                      )
                )
                UPDATE wg_region_inferred_genres inferred
                SET status = 'rejected',
                    raw_payload = inferred.raw_payload || jsonb_build_object(
                        'resolved_existing_variant',
                        jsonb_build_object(
                            'cleanup_model', CAST(:reviewer_model AS text),
                            'resolved_genre_id', inferred_match.genre_id,
                            'resolved_genre_title', inferred_match.genre_title,
                            'reason', 'candidate_has_existing_genre_equivalent'
                        )
                    ),
                    updated_at = now()
                FROM inferred_match
                WHERE inferred.id = inferred_match.inferred_id
                  AND inferred.status <> 'rejected'
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.inferred_variants_resolved = int(inferred_status_result.rowcount or 0)

        fuzzy_base_result = await conn.execute(
            text("""
                WITH candidate AS (
                    SELECT
                        inferred.id AS inferred_id,
                        inferred.region_id,
                        inferred.base_genre_id,
                        inferred.proposed_display_title,
                        base.wikipedia_title AS base_title,
                        regexp_replace(
                            lower(inferred.proposed_display_title),
                            '[^a-z0-9]+',
                            '',
                            'g'
                        ) AS candidate_norm,
                        regexp_replace(
                            lower(base.wikipedia_title),
                            '[^a-z0-9]+',
                            '',
                            'g'
                        ) AS base_norm
                    FROM wg_region_inferred_genres inferred
                    JOIN wg_genres base ON base.id = inferred.base_genre_id
                    JOIN wg_regions region ON region.id = inferred.region_id
                    WHERE inferred.status IN ('proposed', 'accepted')
                      AND coalesce(region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'collapsed',
                        'rejected',
                        'demoted_source',
                        'hidden_from_ui'
                      )
                ),
                equivalent AS (
                    SELECT DISTINCT candidate.*
                    FROM candidate
                    JOIN wg_region_genre_relationships rel
                      ON rel.region_id = candidate.region_id
                     AND rel.genre_id = candidate.base_genre_id
                     AND rel.status = 'accepted'
                    WHERE candidate.candidate_norm <> candidate.base_norm
                      AND candidate.candidate_norm LIKE '%' || candidate.base_norm
                )
                UPDATE wg_region_inferred_genres inferred
                SET status = 'rejected',
                    raw_payload = inferred.raw_payload || jsonb_build_object(
                        'resolved_base_style_equivalent',
                        jsonb_build_object(
                            'cleanup_model', CAST(:reviewer_model AS text),
                            'base_genre_id', equivalent.base_genre_id,
                            'base_genre_title', equivalent.base_title,
                            'reason', 'candidate_fuzzy_matches_existing_region_base_style'
                        )
                    ),
                    updated_at = now()
                FROM equivalent
                WHERE inferred.id = equivalent.inferred_id
                  AND inferred.status <> 'rejected'
            """),
            {"reviewer_model": CLEANUP_MODEL},
        )
        stats.fuzzy_base_equivalent_variants_resolved = int(fuzzy_base_result.rowcount or 0)

    stats.sample = [
        f"status_updates={stats.region_status_updates}",
        f"kind_updates={stats.region_kind_updates}",
        f"title_updates={stats.region_title_updates}",
        f"parent_edges_rejected={stats.parent_edges_rejected}",
        f"region_genre_edges_rejected={stats.region_genre_edges_rejected}",
        f"collapsed_display_edges_rejected={stats.collapsed_display_edges_rejected}",
        f"stale_city_visibility_updates={stats.stale_city_visibility_updates}",
        f"hierarchy_edges_added={stats.hierarchy_edges_added}",
        f"duplicate_region_edges_rejected={stats.duplicate_region_edges_rejected}",
        f"duplicate_region_genre_edges_rejected={stats.duplicate_region_genre_edges_rejected}",
        f"inferred_variant_edges_added={stats.inferred_variant_edges_added}",
        f"inferred_variants_resolved={stats.inferred_variants_resolved}",
        f"fuzzy_base_equivalent_variants_resolved={stats.fuzzy_base_equivalent_variants_resolved}",
    ][:sample_size]
    logger.info("region_post_review_cleanup_complete", **stats.__dict__)
    return stats
