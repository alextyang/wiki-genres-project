"""Full regional hierarchy/accessibility production pass.

This pass applies global hierarchy rules after extraction/review:

- countries are the only manual regional entry points;
- cities and low-value subregions are hidden/collapsed rather than surfaced as
  primary graph clutter;
- special high-subregion countries can expose a richer reviewed subregion set;
- useful superregions remain organizational nodes but are not manual roots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)

COUNTRY_NAMES = {
    "Afghanistan",
    "Albania",
    "Algeria",
    "Andorra",
    "Angola",
    "Antigua and Barbuda",
    "Argentina",
    "Armenia",
    "Australia",
    "Austria",
    "Azerbaijan",
    "Bahamas",
    "Bahrain",
    "Bangladesh",
    "Barbados",
    "Belarus",
    "Belgium",
    "Belize",
    "Benin",
    "Bhutan",
    "Bolivia",
    "Bosnia and Herzegovina",
    "Botswana",
    "Brazil",
    "Brunei",
    "Bulgaria",
    "Burkina Faso",
    "Burundi",
    "Cambodia",
    "Cameroon",
    "Canada",
    "Cape Verde",
    "Central African Republic",
    "Chad",
    "Chile",
    "China",
    "Colombia",
    "Comoros",
    "Costa Rica",
    "Croatia",
    "Cuba",
    "Cyprus",
    "Czech Republic",
    "Democratic Republic of the Congo",
    "Denmark",
    "Djibouti",
    "Dominica",
    "Dominican Republic",
    "Ecuador",
    "Egypt",
    "El Salvador",
    "Equatorial Guinea",
    "Eritrea",
    "Estonia",
    "Eswatini",
    "Ethiopia",
    "Fiji",
    "Finland",
    "France",
    "Gabon",
    "Gambia",
    "Georgia",
    "Germany",
    "Ghana",
    "Greece",
    "Grenada",
    "Guatemala",
    "Guinea",
    "Guinea-Bissau",
    "Guyana",
    "Haiti",
    "Honduras",
    "Hungary",
    "Iceland",
    "India",
    "Indonesia",
    "Iran",
    "Iraq",
    "Ireland",
    "Israel",
    "Italy",
    "Ivory Coast",
    "Jamaica",
    "Japan",
    "Jordan",
    "Kazakhstan",
    "Kenya",
    "Kiribati",
    "Kuwait",
    "Kyrgyzstan",
    "Laos",
    "Latvia",
    "Lebanon",
    "Lesotho",
    "Liberia",
    "Libya",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Madagascar",
    "Malawi",
    "Malaysia",
    "Maldives",
    "Mali",
    "Malta",
    "Marshall Islands",
    "Mauritania",
    "Mauritius",
    "Mexico",
    "Micronesia",
    "Moldova",
    "Monaco",
    "Mongolia",
    "Montenegro",
    "Morocco",
    "Mozambique",
    "Myanmar",
    "Namibia",
    "Nauru",
    "Nepal",
    "Netherlands",
    "New Zealand",
    "Nicaragua",
    "Niger",
    "Nigeria",
    "North Korea",
    "North Macedonia",
    "Norway",
    "Oman",
    "Pakistan",
    "Palau",
    "Palestine",
    "Panama",
    "Papua New Guinea",
    "Paraguay",
    "Peru",
    "Philippines",
    "Poland",
    "Portugal",
    "Qatar",
    "Republic of the Congo",
    "Romania",
    "Russia",
    "Rwanda",
    "Saint Kitts and Nevis",
    "Saint Lucia",
    "Saint Vincent and the Grenadines",
    "Samoa",
    "San Marino",
    "Saudi Arabia",
    "Senegal",
    "Serbia",
    "Seychelles",
    "Sierra Leone",
    "Singapore",
    "Slovakia",
    "Slovenia",
    "Solomon Islands",
    "Somalia",
    "South Africa",
    "South Korea",
    "South Sudan",
    "Spain",
    "Sri Lanka",
    "Sudan",
    "Suriname",
    "Sweden",
    "Switzerland",
    "Syria",
    "Taiwan",
    "Tajikistan",
    "Tanzania",
    "Thailand",
    "Timor-Leste",
    "Togo",
    "Tonga",
    "Trinidad and Tobago",
    "Tunisia",
    "Turkey",
    "Turkmenistan",
    "Tuvalu",
    "Uganda",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "Uruguay",
    "Uzbekistan",
    "Vanuatu",
    "Vatican City",
    "Venezuela",
    "Vietnam",
    "Yemen",
    "Zambia",
    "Zimbabwe",
}

TERRITORY_NAMES = {
    "American Samoa",
    "Anguilla",
    "Aruba",
    "Bermuda",
    "British Virgin Islands",
    "Cayman Islands",
    "Cook Islands",
    "Curaçao",
    "Falkland Islands",
    "Faroe Islands",
    "French Guiana",
    "French Polynesia",
    "Gibraltar",
    "Greenland",
    "Guadeloupe",
    "Guam",
    "Hong Kong",
    "Isle of Man",
    "Macau",
    "Martinique",
    "Montserrat",
    "New Caledonia",
    "Northern Mariana Islands",
    "Puerto Rico",
    "Réunion",
    "Saint Pierre and Miquelon",
    "Sint Maarten",
    "Turks and Caicos Islands",
    "United States Virgin Islands",
    "Virgin Islands",
    "Wallis and Futuna",
}

US_SUBREGION_NAMES = {
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia (U.S. state)",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York (state)",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington (state)",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
}

SPECIAL_MAP_COUNTRY_NAMES = {
    "Canada",
    "China",
    "France",
    "India",
    "Italy",
    "Spain",
    "United Kingdom",
    "United States",
}

SUBREGION_KIND_SPECIAL_MAP_COUNTRY_NAMES = {
    "China",
    "India",
    "United States",
}

VALUABLE_SUPERREGION_NAMES = {
    "Africa",
    "Ancient",
    "Asia",
    "Caribbean",
    "Central America",
    "East Africa",
    "East Asia",
    "Europe",
    "Latin America",
    "Middle East",
    "North Africa",
    "North America",
    "Oceania",
    "South America",
    "South Asia",
    "Southeast Asia",
    "Southern Africa",
    "West Africa",
}

SPECIAL_REGION_PARENT_NAMES = {
    "Andes": "South America",
    "Assyria": "Middle East",
    "Berber cultural region": "North Africa",
    "Crimean Tatar": "Ukraine",
    "Himalayas": "South Asia",
    "Meitei": "India",
    "Mesopotamia": "Middle East",
    "Renaissance": "Europe",
    "al-Andalus": "Spain",
}

INVALID_TITLE_REPLACEMENTS = {
    "Ancient": "Ancient music",
    "Georgian Bath": "Music of Georgian Bath",
    "Greek mythology": "Music of Greek mythology",
    "Kerala": "Music of Kerala",
    "Oceanic and Australian": "Oceanic and Australian music",
    "Sub-Saharan African": "Music of Sub-Saharan Africa",
    "sub-saharan african": "Music of Sub-Saharan Africa",
}

COLLAPSE_TO_REGION = {
    "central american": "Central America",
}

OWNED_RELATION_FILTER = "('regional_style_mention', 'influence_or_context')"


@dataclass
class RegionHierarchyPassStats:
    dry_run: bool = False
    regions_seen: int = 0
    country_kind_updates: int = 0
    territory_kind_updates: int = 0
    special_map_subregions_promoted: int = 0
    superregions_approved: int = 0
    low_value_regions_collapsed: int = 0
    low_value_relationships_copied: int = 0
    child_relationships_reparented: int = 0
    redundant_parent_edges_rejected: int = 0
    explicit_parent_edges_added: int = 0
    invalid_titles_fixed: int = 0
    source_regions_collapsed: int = 0
    style_proxy_regions_demoted: int = 0
    accessibility_rows_marked: int = 0
    sample: list[str] = field(default_factory=list)


def normalized_name(name: str | None) -> str:
    return " ".join((name or "").strip().casefold().split())


def reviewed_kind_for_name(name: str, current_kind: str) -> str:
    if name in COUNTRY_NAMES:
        return "country"
    if name in TERRITORY_NAMES:
        return "territory"
    if name in US_SUBREGION_NAMES and current_kind in {"unknown", "territory"}:
        return "subregion"
    return current_kind


def is_valuable_superregion(
    *,
    name: str,
    kind: str,
    owned_count: int,
    child_count: int,
    country_child_count: int,
) -> bool:
    return (
        kind == "continent"
        or name in VALUABLE_SUPERREGION_NAMES
        or country_child_count >= 2
        or child_count >= 8
        or (kind in {"cultural_region", "subregion"} and child_count >= 5 and owned_count >= 1)
    )


def is_low_value_collapsible(
    *,
    name: str,
    kind: str,
    owned_count: int,
    candidate_count: int,
    child_count: int,
    country_parent_count: int,
    has_united_states_parent: bool,
    has_special_map_parent: bool = False,
) -> bool:
    if kind in {"country", "continent", "city"}:
        return False
    total_signals = owned_count + candidate_count + child_count
    if has_special_map_parent and total_signals > 0:
        return False
    if is_valuable_superregion(
        name=name,
        kind=kind,
        owned_count=owned_count,
        child_count=child_count,
        country_child_count=0,
    ):
        return False
    if country_parent_count > 0 and total_signals <= 1:
        return True
    if candidate_count > 0:
        return False
    if kind in {"cultural_region", "diaspora_region", "historical_region"}:
        return owned_count == 0 and child_count == 0 and country_parent_count > 0
    return country_parent_count > 0 and owned_count < 2 and child_count < 3


async def apply_region_hierarchy_accessibility_pass(
    *,
    dry_run: bool = False,
    sample_size: int = 25,
) -> RegionHierarchyPassStats:
    """Apply full-region hierarchy/accessibility heuristics to every region."""
    await apply_migrations()
    stats = RegionHierarchyPassStats(dry_run=dry_run)
    engine = get_engine()
    async with engine.begin() as conn:
        country_names = sorted(COUNTRY_NAMES)
        territory_names = sorted(TERRITORY_NAMES)
        special_map_country_names = sorted(SPECIAL_MAP_COUNTRY_NAMES)
        subregion_kind_special_map_country_names = sorted(SUBREGION_KIND_SPECIAL_MAP_COUNTRY_NAMES)
        superregion_names = sorted(VALUABLE_SUPERREGION_NAMES)

        rows = (
            (
                await conn.execute(
                    text("""
                        WITH owned AS (
                            SELECT region_id, count(*) AS owned_count
                            FROM wg_region_genre_relationships
                            WHERE status = 'accepted'
                              AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                            GROUP BY region_id
                        ),
                        candidates AS (
                            SELECT region_id, count(*) AS candidate_count
                            FROM wg_region_inferred_genres
                            WHERE status IN ('accepted', 'needs_review', 'proposed')
                            GROUP BY region_id
                        ),
                        child AS (
                            SELECT
                                rel.to_region_id AS region_id,
                                count(*) FILTER (
                                    WHERE coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                                        'collapsed',
                                        'rejected',
                                        'demoted_source',
                                        'hidden_from_ui'
                                    )
                                      AND coalesce(child.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                                        'collapsed',
                                        'rejected',
                                        'demoted_source',
                                        'hidden_from_ui'
                                    )
                                ) AS child_count,
                                count(*) FILTER (
                                    WHERE child.kind = 'country'
                                      AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                                        'collapsed',
                                        'rejected',
                                        'demoted_source',
                                        'hidden_from_ui'
                                    )
                                      AND coalesce(child.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                                        'collapsed',
                                        'rejected',
                                        'demoted_source',
                                        'hidden_from_ui'
                                    )
                                ) AS country_child_count
                            FROM wg_region_relationships rel
                            JOIN wg_regions child ON child.id = rel.from_region_id
                            WHERE rel.status = 'accepted'
                            GROUP BY rel.to_region_id
                        ),
                        parent AS (
                            SELECT
                                rel.from_region_id AS region_id,
                                count(*) AS parent_count,
                                count(*) FILTER (WHERE parent.kind = 'country') AS country_parent_count,
                                bool_or(parent.canonical_name = 'United States') AS has_united_states_parent,
                                bool_or(parent.canonical_name = ANY(:special_map_country_names)) AS has_special_map_parent
                            FROM wg_region_relationships rel
                            JOIN wg_regions parent ON parent.id = rel.to_region_id
                            WHERE rel.status = 'accepted'
                            GROUP BY rel.from_region_id
                        )
                        SELECT
                            r.id,
                            r.canonical_name,
                            r.kind,
                            r.wikipedia_title,
                            coalesce(r.raw_payload #>> '{region_production_review,status}', '') AS review_status,
                            coalesce(owned.owned_count, 0) AS owned_count,
                            coalesce(candidates.candidate_count, 0) AS candidate_count,
                            coalesce(child.child_count, 0) AS child_count,
                            coalesce(child.country_child_count, 0) AS country_child_count,
                            coalesce(parent.parent_count, 0) AS parent_count,
                            coalesce(parent.country_parent_count, 0) AS country_parent_count,
                            coalesce(parent.has_united_states_parent, false) AS has_united_states_parent,
                            coalesce(parent.has_special_map_parent, false) AS has_special_map_parent
                        FROM wg_regions r
                        LEFT JOIN owned ON owned.region_id = r.id
                        LEFT JOIN candidates ON candidates.region_id = r.id
                        LEFT JOIN child ON child.region_id = r.id
                        LEFT JOIN parent ON parent.region_id = r.id
                        WHERE coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                            'collapsed',
                            'rejected',
                            'demoted_source'
                        )
                        ORDER BY r.kind, r.canonical_name
                    """)
                    ,
                    {"special_map_country_names": special_map_country_names},
                )
            )
            .mappings()
            .fetchall()
        )
        stats.regions_seen = len(rows)

        if dry_run:
            for row in rows:
                desired = reviewed_kind_for_name(row["canonical_name"], row["kind"])
                if desired != row["kind"] and len(stats.sample) < sample_size:
                    stats.sample.append(f"kind:{row['canonical_name']} {row['kind']} -> {desired}")
                if desired == "country" and desired != row["kind"]:
                    stats.country_kind_updates += 1
                elif desired == "territory" and desired != row["kind"]:
                    stats.territory_kind_updates += 1
                if row["has_special_map_parent"]:
                    stats.special_map_subregions_promoted += 1
                if is_low_value_collapsible(
                    name=row["canonical_name"],
                    kind=desired,
                    owned_count=row["owned_count"],
                    candidate_count=row["candidate_count"],
                    child_count=row["child_count"],
                    country_parent_count=row["country_parent_count"],
                    has_united_states_parent=row["has_united_states_parent"],
                    has_special_map_parent=row["has_special_map_parent"],
                ):
                    stats.low_value_regions_collapsed += 1
            return stats

        country_result = await conn.execute(
            text("""
                UPDATE wg_regions
                SET kind = 'country',
                    raw_payload = jsonb_set(
                        coalesce(raw_payload, '{}'::jsonb),
                        '{region_accessibility}',
                        coalesce(raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', true,
                                'ui_visibility', 'manual_country',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE canonical_name = ANY(:country_names)
                  AND kind <> 'country'
            """),
            {"country_names": country_names},
        )
        stats.country_kind_updates = int(country_result.rowcount or 0)

        territory_result = await conn.execute(
            text("""
                UPDATE wg_regions
                SET kind = 'territory',
                    raw_payload = jsonb_set(
                        coalesce(raw_payload, '{}'::jsonb),
                        '{region_accessibility}',
                        coalesce(raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'country_child',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE canonical_name = ANY(:territory_names)
                  AND kind NOT IN ('country', 'territory')
            """),
            {"territory_names": territory_names},
        )
        stats.territory_kind_updates = int(territory_result.rowcount or 0)

        await conn.execute(
            text("""
                UPDATE wg_regions
                SET raw_payload = jsonb_set(
                        coalesce(raw_payload, '{}'::jsonb) #- '{region_accessibility,special_map}',
                        '{region_accessibility}',
                        coalesce(raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            - 'special_map'
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'country_child',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE coalesce(raw_payload #>> '{region_accessibility,ui_visibility}', '') = 'special_country_subregion'
            """)
        )

        special_map_result = await conn.execute(
            text("""
                WITH owned AS (
                    SELECT region_id, count(DISTINCT genre_id) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND coalesce(raw_payload->>'graph_edge', 'true') <> 'false'
                    GROUP BY region_id
                ),
                candidates AS (
                    SELECT region_id, count(DISTINCT base_genre_id) AS candidate_count
                    FROM wg_region_inferred_genres
                    WHERE status IN ('accepted', 'needs_review', 'proposed')
                    GROUP BY region_id
                ),
                child_counts AS (
                    SELECT rel.to_region_id AS region_id, count(DISTINCT rel.from_region_id) AS child_count
                    FROM wg_region_relationships rel
                    JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                      AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                      AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                    GROUP BY rel.to_region_id
                ),
                map_child AS (
                    SELECT DISTINCT
                        child.id AS child_region_id,
                        parent.canonical_name AS parent_name
                    FROM wg_region_relationships rel
                    JOIN wg_regions child ON child.id = rel.from_region_id
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    LEFT JOIN owned ON owned.region_id = child.id
                    LEFT JOIN candidates ON candidates.region_id = child.id
                    LEFT JOIN child_counts ON child_counts.region_id = child.id
                    WHERE rel.status = 'accepted'
                      AND parent.canonical_name = ANY(:special_map_country_names)
                      AND child.kind IN ('subregion', 'territory', 'unknown')
                      AND child.wikipedia_title ~* '^Music (of|in) '
                      AND coalesce(rel.source_title, '') !~* 'by (city|populated place)'
                      AND (
                          coalesce(rel.source_title, '') ~* 'by (state|province|territory|region|autonomous community|federal subject|department|county|state or union territory|province or territory)'
                          OR child.kind = 'territory'
                          OR (
                              child.kind = 'subregion'
                              AND parent.canonical_name = ANY(:subregion_kind_special_map_country_names)
                          )
                      )
                      AND (
                          coalesce(owned.owned_count, 0)
                          + coalesce(candidates.candidate_count, 0)
                          + coalesce(child_counts.child_count, 0)
                      ) > 0
                      AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                      AND coalesce(child.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                UPDATE wg_regions child
                SET kind = CASE
                        WHEN child.kind = 'unknown' THEN 'subregion'
                        ELSE child.kind
                    END,
                    raw_payload = jsonb_set(
                        coalesce(child.raw_payload, '{}'::jsonb) #- '{region_production_review}',
                        '{region_accessibility}',
                        coalesce(child.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'special_country_subregion',
                                'special_map',
                                    regexp_replace(
                                        lower(map_child.parent_name),
                                        '[^a-z0-9]+',
                                        '_',
                                        'g'
                                    ) || '_subregions',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM map_child
                WHERE map_child.child_region_id = child.id
            """),
            {
                "special_map_country_names": special_map_country_names,
                "subregion_kind_special_map_country_names": subregion_kind_special_map_country_names,
            },
        )
        stats.special_map_subregions_promoted = int(special_map_result.rowcount or 0)

        super_result = await conn.execute(
            text("""
                WITH child_counts AS (
                    SELECT
                        rel.to_region_id AS region_id,
                        count(*) AS child_count,
                        count(*) FILTER (WHERE child.kind = 'country') AS country_child_count
                    FROM wg_region_relationships rel
                    JOIN wg_regions child ON child.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                    GROUP BY rel.to_region_id
                ),
                owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                ),
                eligible AS (
                    SELECT r.id
                    FROM wg_regions r
                    LEFT JOIN child_counts child ON child.region_id = r.id
                    LEFT JOIN owned ON owned.region_id = r.id
                    WHERE coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                        'collapsed',
                        'rejected',
                        'demoted_source'
                    )
                      AND (
                        r.kind = 'continent'
                        OR r.canonical_name = ANY(:superregion_names)
                        OR coalesce(child.country_child_count, 0) >= 2
                        OR coalesce(child.child_count, 0) >= 8
                        OR (
                            r.kind IN ('cultural_region', 'subregion')
                            AND coalesce(child.child_count, 0) >= 5
                            AND coalesce(owned.owned_count, 0) >= 1
                        )
                      )
                      AND coalesce(r.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'special_country_subregion'
                )
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(r.raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status', 'approved_superregion',
                                    'reason', 'full_region_hierarchy_pass',
                                    'reviewer_model', 'region-hierarchy-accessibility-v1'
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'superregion_child_access',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM eligible
                WHERE eligible.id = r.id
                  AND r.kind <> 'country'
            """),
            {"superregion_names": superregion_names},
        )
        stats.superregions_approved = int(super_result.rowcount or 0)

        parent_values = [
            {"child_name": child_name, "parent_name": parent_name}
            for child_name, parent_name in sorted(SPECIAL_REGION_PARENT_NAMES.items())
        ]
        explicit_parent_edges = await conn.execute(
            text("""
                WITH requested(child_name, parent_name) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:parent_values AS jsonb))
                        AS item(child_name text, parent_name text)
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
                    child.id,
                    parent.id,
                    CASE
                        WHEN child.kind = 'historical_region' THEN 'historical_region_of'
                        WHEN child.kind IN ('cultural_region', 'diaspora_region') THEN 'cultural_region_of'
                        ELSE 'part_of'
                    END,
                    'manual',
                    'Full region hierarchy pass',
                    child.canonical_name || ' anchored to ' || parent.canonical_name
                        || ' by full-region hierarchy heuristic.',
                    0.84,
                    'accepted',
                    'Explicit parent selected by full hierarchy/accessibility pass.',
                    'region-hierarchy-accessibility-v1',
                    jsonb_build_object('hierarchy_pass', 'region-hierarchy-accessibility-v1')
                FROM requested
                JOIN wg_regions child ON child.canonical_name = requested.child_name
                JOIN wg_regions parent ON parent.canonical_name = requested.parent_name
                WHERE child.id <> parent.id
                  AND coalesce(child.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                      'collapsed',
                      'rejected',
                      'demoted_source'
                  )
                ON CONFLICT DO NOTHING
            """),
            {"parent_values": json.dumps(parent_values)},
        )
        stats.explicit_parent_edges_added = int(explicit_parent_edges.rowcount or 0)

        title_values = [
            {"region_name": region_name, "title": title}
            for region_name, title in sorted(INVALID_TITLE_REPLACEMENTS.items())
        ]
        fixed_titles = await conn.execute(
            text("""
                WITH requested(region_name, title) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:title_values AS jsonb))
                        AS item(region_name text, title text)
                )
                UPDATE wg_regions r
                SET wikipedia_title = requested.title,
                    raw_payload = jsonb_set(
                        coalesce(r.raw_payload, '{}'::jsonb),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'title_cleanup', 'full_region_hierarchy_pass',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM requested
                WHERE r.canonical_name = requested.region_name
                  AND r.wikipedia_title IS DISTINCT FROM requested.title
            """),
            {"title_values": json.dumps(title_values)},
        )
        stats.invalid_titles_fixed = int(fixed_titles.rowcount or 0)
        await conn.execute(
            text("""
                WITH requested(region_name, title) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:title_values AS jsonb))
                        AS item(region_name text, title text)
                ),
                target AS (
                    SELECT
                        r.id AS region_id,
                        p.genre_id,
                        requested.title
                    FROM requested
                    JOIN wg_regions r ON r.canonical_name = requested.region_name
                    JOIN wg_region_promoted_genres p ON p.region_id = r.id
                ),
                updated_promoted AS (
                    UPDATE wg_region_promoted_genres p
                    SET wikipedia_title = target.title,
                        promotion_rule = 'reviewed_region_title'
                    FROM target
                    WHERE p.region_id = target.region_id
                      AND p.wikipedia_title IS DISTINCT FROM target.title
                    RETURNING p.genre_id, p.wikipedia_title
                )
                UPDATE wg_genres g
                SET wikipedia_title = target.title,
                    wikipedia_url = 'https://en.wikipedia.org/wiki/' || replace(target.title, ' ', '_')
                FROM target
                WHERE g.id = target.genre_id
                  AND g.wikipedia_title IS DISTINCT FROM target.title
            """),
            {"title_values": json.dumps(title_values)},
        )

        collapse_values = [
            {"source_name": source_name, "target_name": target_name}
            for source_name, target_name in sorted(COLLAPSE_TO_REGION.items())
        ]
        collapsed_sources = await conn.execute(
            text("""
                WITH requested(source_name, target_name) AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:collapse_values AS jsonb))
                        AS item(source_name text, target_name text)
                )
                UPDATE wg_regions source
                SET raw_payload = jsonb_set(
                        coalesce(source.raw_payload, '{}'::jsonb),
                        '{region_production_review}',
                        coalesce(source.raw_payload #> '{region_production_review}', '{}'::jsonb)
                            || jsonb_build_object(
                                'status', 'collapsed',
                                'reason', 'list_source_collapsed_to_canonical_region',
                                'target_region', target.id,
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM requested
                JOIN wg_regions target ON target.canonical_name = requested.target_name
                WHERE source.canonical_name = requested.source_name
            """),
            {"collapse_values": json.dumps(collapse_values)},
        )
        stats.source_regions_collapsed = int(collapsed_sources.rowcount or 0)

        demoted_style_proxies = await conn.execute(
            text("""
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        coalesce(r.raw_payload, '{}'::jsonb),
                        '{region_production_review}',
                        coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                            || jsonb_build_object(
                                'status', 'demoted_source',
                                'reason', 'style_proxy_not_regional_access_node',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                WHERE r.kind = 'unknown'
                  AND r.wikipedia_title !~* '^Music (of|in) '
                  AND r.wikipedia_title ~* 'folk music$'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM wg_region_relationships rel
                      WHERE rel.status = 'accepted'
                        AND rel.from_region_id = r.id
                  )
            """)
        )
        stats.style_proxy_regions_demoted = int(demoted_style_proxies.rowcount or 0)

        # Collapse demonym/style proxy regions (e.g. "South Korean") into their
        # single country parent. These are typically list/category artifacts
        # and should not be exposed as navigable regional nodes.
        proxy_merged_genres = await conn.execute(
            text("""
                WITH proxy AS (
                    SELECT
                        r.id AS proxy_region_id,
                        r.canonical_name AS proxy_name,
                        r.wikipedia_title AS proxy_title,
                        parent.id AS parent_region_id,
                        parent.canonical_name AS parent_name
                    FROM wg_regions r
                    JOIN LATERAL (
                        SELECT rel.to_region_id
                        FROM wg_region_relationships rel
                        WHERE rel.status = 'accepted'
                          AND rel.from_region_id = r.id
                        ORDER BY rel.confidence DESC, rel.to_region_id
                        LIMIT 2
                    ) parent_rel ON true
                    JOIN wg_regions parent ON parent.id = parent_rel.to_region_id
                    WHERE r.kind IN ('unknown', 'subregion', 'cultural_region')
                      AND parent.kind = 'country'
                      AND r.wikipedia_title !~* '^Music (of|in) '
                      AND (
                          r.wikipedia_title ~* 'folk music$'
                          OR r.wikipedia_title ~* 'styles of music$'
                          OR r.wikipedia_title ~* 'music traditions$'
                          OR r.wikipedia_title ~* 'traditional music$'
                      )
                      AND (
                          SELECT count(DISTINCT rel2.to_region_id)
                          FROM wg_region_relationships rel2
                          WHERE rel2.status = 'accepted'
                            AND rel2.from_region_id = r.id
                      ) = 1
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                INSERT INTO wg_region_genre_relationships (
                    region_id,
                    genre_id,
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
                SELECT DISTINCT
                    proxy.parent_region_id,
                    rel.genre_id,
                    CASE
                        WHEN proxy.proxy_title ~* 'folk music$'
                          OR proxy.proxy_title ~* 'traditional music$'
                          OR proxy.proxy_title ~* 'music traditions$'
                        THEN 'traditional_region'
                        ELSE rel.relation
                    END,
                    'manual',
                    'Full region hierarchy pass',
                    'Merged from demonym/style proxy region ' || proxy.proxy_name
                        || ' into ' || proxy.parent_name || '.',
                    least(rel.confidence, 0.76),
                    'accepted',
                    'Merged upward from demonym/style proxy region during full hierarchy/accessibility pass.',
                    'region-hierarchy-accessibility-v1',
                    jsonb_build_object(
                        'source_region_id', proxy.proxy_region_id,
                        'source_region_name', proxy.proxy_name,
                        'hierarchy_pass', 'region-hierarchy-accessibility-v1',
                        'proxy_merge', true
                    )
                FROM proxy
                JOIN wg_region_genre_relationships rel ON rel.region_id = proxy.proxy_region_id
                WHERE rel.status = 'accepted'
                ON CONFLICT DO NOTHING
            """)
        )
        stats.low_value_relationships_copied += int(proxy_merged_genres.rowcount or 0)

        proxy_reparented_children = await conn.execute(
            text("""
                WITH proxy AS (
                    SELECT
                        r.id AS proxy_region_id,
                        parent.id AS parent_region_id
                    FROM wg_regions r
                    JOIN wg_region_relationships relp
                      ON relp.status = 'accepted'
                     AND relp.from_region_id = r.id
                    JOIN wg_regions parent ON parent.id = relp.to_region_id
                    WHERE r.kind IN ('unknown', 'subregion', 'cultural_region')
                      AND parent.kind = 'country'
                      AND r.wikipedia_title !~* '^Music (of|in) '
                      AND (
                          r.wikipedia_title ~* 'folk music$'
                          OR r.wikipedia_title ~* 'styles of music$'
                          OR r.wikipedia_title ~* 'music traditions$'
                          OR r.wikipedia_title ~* 'traditional music$'
                      )
                      AND (
                          SELECT count(DISTINCT rel2.to_region_id)
                          FROM wg_region_relationships rel2
                          WHERE rel2.status = 'accepted'
                            AND rel2.from_region_id = r.id
                      ) = 1
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
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
                SELECT DISTINCT
                    rel.from_region_id,
                    proxy.parent_region_id,
                    rel.relation,
                    'manual',
                    'Full region hierarchy pass',
                    'Reparented from demonym/style proxy region during full hierarchy/accessibility pass.',
                    least(rel.confidence, 0.76),
                    'accepted',
                    'Reparented from demonym/style proxy region during full hierarchy/accessibility pass.',
                    'region-hierarchy-accessibility-v1',
                    jsonb_build_object(
                        'collapsed_parent_region_id', proxy.proxy_region_id,
                        'hierarchy_pass', 'region-hierarchy-accessibility-v1',
                        'proxy_merge', true
                    )
                FROM proxy
                JOIN wg_region_relationships rel
                  ON rel.status = 'accepted'
                 AND rel.to_region_id = proxy.proxy_region_id
                JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                WHERE rel.from_region_id <> proxy.parent_region_id
                  AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                      'collapsed',
                      'rejected',
                      'demoted_source',
                      'hidden_from_ui'
                  )
                  AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                      'collapsed',
                      'rejected',
                      'demoted_source',
                      'hidden_from_ui'
                  )
                ON CONFLICT DO NOTHING
            """)
        )
        stats.child_relationships_reparented += int(proxy_reparented_children.rowcount or 0)

        proxy_edges_rejected = await conn.execute(
            text("""
                WITH proxy AS (
                    SELECT
                        r.id AS proxy_region_id
                    FROM wg_regions r
                    JOIN wg_region_relationships relp
                      ON relp.status = 'accepted'
                     AND relp.from_region_id = r.id
                    JOIN wg_regions parent ON parent.id = relp.to_region_id
                    WHERE r.kind IN ('unknown', 'subregion', 'cultural_region')
                      AND parent.kind = 'country'
                      AND r.wikipedia_title !~* '^Music (of|in) '
                      AND (
                          r.wikipedia_title ~* 'folk music$'
                          OR r.wikipedia_title ~* 'styles of music$'
                          OR r.wikipedia_title ~* 'music traditions$'
                          OR r.wikipedia_title ~* 'traditional music$'
                      )
                      AND (
                          SELECT count(DISTINCT rel2.to_region_id)
                          FROM wg_region_relationships rel2
                          WHERE rel2.status = 'accepted'
                            AND rel2.from_region_id = r.id
                      ) = 1
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                UPDATE wg_region_relationships rel
                SET status = 'rejected',
                    review_reason = 'Rejected by full hierarchy pass: demonym/style proxy collapsed into country.',
                    reviewer_model = 'region-hierarchy-accessibility-v1',
                    updated_at = now()
                FROM proxy
                WHERE rel.status = 'accepted'
                  AND (rel.from_region_id = proxy.proxy_region_id OR rel.to_region_id = proxy.proxy_region_id)
            """)
        )
        stats.redundant_parent_edges_rejected += int(proxy_edges_rejected.rowcount or 0)

        proxy_collapsed = await conn.execute(
            text("""
                WITH proxy AS (
                    SELECT
                        r.id AS proxy_region_id
                    FROM wg_regions r
                    JOIN wg_region_relationships relp
                      ON relp.status = 'rejected'
                     AND relp.reviewer_model = 'region-hierarchy-accessibility-v1'
                     AND relp.from_region_id = r.id
                    WHERE r.kind IN ('unknown', 'subregion', 'cultural_region')
                      AND r.wikipedia_title !~* '^Music (of|in) '
                      AND (
                          r.wikipedia_title ~* 'folk music$'
                          OR r.wikipedia_title ~* 'styles of music$'
                          OR r.wikipedia_title ~* 'music traditions$'
                          OR r.wikipedia_title ~* 'traditional music$'
                      )
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(r.raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status', 'collapsed',
                                    'reason', 'demonym_style_proxy_collapsed_to_country',
                                    'reviewer_model', 'region-hierarchy-accessibility-v1'
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'collapsed',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM proxy
                WHERE r.id = proxy.proxy_region_id
            """)
        )
        stats.low_value_regions_collapsed += int(proxy_collapsed.rowcount or 0)

        # Merge low-value subregion/territory/unknown nodes into their most
        # specific country parent before collapsing them away from the UI.
        copied_edges = await conn.execute(
            text("""
                WITH owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                ),
                child_counts AS (
                    SELECT rel.to_region_id AS region_id, count(*) AS child_count
                    FROM wg_region_relationships rel
                    JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                      AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                      AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                    GROUP BY rel.to_region_id
                ),
                candidates AS (
                    SELECT region_id, count(*) AS candidate_count
                    FROM wg_region_inferred_genres
                    WHERE status IN ('accepted', 'needs_review', 'proposed')
                    GROUP BY region_id
                ),
                country_parent AS (
                    SELECT DISTINCT ON (rel.from_region_id)
                        rel.from_region_id AS region_id,
                        parent.id AS parent_region_id,
                        parent.canonical_name AS parent_name
                    FROM wg_region_relationships rel
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    WHERE rel.status = 'accepted'
                      AND parent.kind = 'country'
                    ORDER BY rel.from_region_id, rel.confidence DESC, parent.canonical_name
                ),
                collapsible AS (
                    SELECT
                        r.id AS region_id,
                        r.canonical_name,
                        cp.parent_region_id,
                        cp.parent_name
                    FROM wg_regions r
                    JOIN country_parent cp ON cp.region_id = r.id
                    LEFT JOIN owned o ON o.region_id = r.id
                    LEFT JOIN child_counts c ON c.region_id = r.id
                    LEFT JOIN candidates candidate_counts ON candidate_counts.region_id = r.id
                    WHERE r.kind IN (
                          'subregion',
                          'territory',
                          'unknown',
                          'cultural_region',
                          'diaspora_region',
                          'historical_region',
                          'language_region'
                      )
                      AND coalesce(r.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'special_country_subregion'
                      AND (
                          (
                              coalesce(o.owned_count, 0)
                              + coalesce(candidate_counts.candidate_count, 0)
                              + coalesce(c.child_count, 0)
                          ) <= 1
                          OR (
                              coalesce(candidate_counts.candidate_count, 0) = 0
                              AND coalesce(o.owned_count, 0) < 2
                              AND coalesce(c.child_count, 0) < 3
                          )
                      )
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                INSERT INTO wg_region_genre_relationships (
                    region_id,
                    genre_id,
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
                SELECT DISTINCT
                    collapsible.parent_region_id,
                    rel.genre_id,
                    rel.relation,
                    'manual',
                    'Full region hierarchy pass',
                    'Merged from low-value subregion ' || collapsible.canonical_name
                        || ' into ' || collapsible.parent_name || '.',
                    least(rel.confidence, 0.76),
                    'accepted',
                    'Merged upward from low-value subregion during full hierarchy/accessibility pass.',
                    'region-hierarchy-accessibility-v1',
                    jsonb_build_object(
                        'source_region_id', collapsible.region_id,
                        'source_region_name', collapsible.canonical_name,
                        'hierarchy_pass', 'region-hierarchy-accessibility-v1'
                    )
                FROM collapsible
                JOIN wg_region_genre_relationships rel ON rel.region_id = collapsible.region_id
                WHERE rel.status = 'accepted'
                  AND rel.relation NOT IN ('regional_style_mention', 'influence_or_context')
                ON CONFLICT DO NOTHING
            """),
        )
        stats.low_value_relationships_copied = int(copied_edges.rowcount or 0)

        reparented_children = await conn.execute(
            text("""
                WITH owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                ),
                child_counts AS (
                    SELECT rel.to_region_id AS region_id, count(*) AS child_count
                    FROM wg_region_relationships rel
                    JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                      AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                      AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                    GROUP BY rel.to_region_id
                ),
                candidates AS (
                    SELECT region_id, count(*) AS candidate_count
                    FROM wg_region_inferred_genres
                    WHERE status IN ('accepted', 'needs_review', 'proposed')
                    GROUP BY region_id
                ),
                country_parent AS (
                    SELECT DISTINCT ON (rel.from_region_id)
                        rel.from_region_id AS region_id,
                        parent.id AS parent_region_id,
                        parent.canonical_name AS parent_name
                    FROM wg_region_relationships rel
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    WHERE rel.status = 'accepted'
                      AND parent.kind = 'country'
                    ORDER BY rel.from_region_id, rel.confidence DESC, parent.canonical_name
                ),
                collapsible AS (
                    SELECT r.id AS region_id, cp.parent_region_id, r.canonical_name
                    FROM wg_regions r
                    JOIN country_parent cp ON cp.region_id = r.id
                    LEFT JOIN owned o ON o.region_id = r.id
                    LEFT JOIN child_counts c ON c.region_id = r.id
                    LEFT JOIN candidates candidate_counts ON candidate_counts.region_id = r.id
                    WHERE r.kind IN (
                          'subregion',
                          'territory',
                          'unknown',
                          'cultural_region',
                          'diaspora_region',
                          'historical_region',
                          'language_region'
                      )
                      AND coalesce(r.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'special_country_subregion'
                      AND (
                          (
                              coalesce(o.owned_count, 0)
                              + coalesce(candidate_counts.candidate_count, 0)
                              + coalesce(c.child_count, 0)
                          ) <= 1
                          OR (
                              coalesce(candidate_counts.candidate_count, 0) = 0
                              AND coalesce(o.owned_count, 0) < 2
                              AND coalesce(c.child_count, 0) < 3
                          )
                      )
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
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
                SELECT DISTINCT
                    rel.from_region_id,
                    collapsible.parent_region_id,
                    rel.relation,
                    'manual',
                    'Full region hierarchy pass',
                    'Reparented from collapsed low-value subregion '
                        || collapsible.canonical_name || '.',
                    least(rel.confidence, 0.76),
                    'accepted',
                    'Reparented from collapsed low-value subregion during full hierarchy/accessibility pass.',
                    'region-hierarchy-accessibility-v1',
                    jsonb_build_object(
                        'collapsed_parent_region_id', collapsible.region_id,
                        'hierarchy_pass', 'region-hierarchy-accessibility-v1'
                    )
                FROM collapsible
                JOIN wg_region_relationships rel ON rel.to_region_id = collapsible.region_id
                JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                WHERE rel.status = 'accepted'
                  AND rel.from_region_id <> collapsible.parent_region_id
                  AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                      'collapsed',
                      'rejected',
                      'demoted_source',
                      'hidden_from_ui'
                  )
                  AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                      'collapsed',
                      'rejected',
                      'demoted_source',
                      'hidden_from_ui'
                  )
                ON CONFLICT DO NOTHING
            """),
        )
        stats.child_relationships_reparented = int(reparented_children.rowcount or 0)

        collapsed = await conn.execute(
            text("""
                WITH owned AS (
                    SELECT region_id, count(*) AS owned_count
                    FROM wg_region_genre_relationships
                    WHERE status = 'accepted'
                      AND relation NOT IN ('regional_style_mention', 'influence_or_context')
                    GROUP BY region_id
                ),
                child_counts AS (
                    SELECT rel.to_region_id AS region_id, count(*) AS child_count
                    FROM wg_region_relationships rel
                    JOIN wg_regions child_region ON child_region.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                      AND coalesce(child_region.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                      AND coalesce(child_region.raw_payload #>> '{region_accessibility,ui_visibility}', '') NOT IN (
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                    GROUP BY rel.to_region_id
                ),
                candidates AS (
                    SELECT region_id, count(*) AS candidate_count
                    FROM wg_region_inferred_genres
                    WHERE status IN ('accepted', 'needs_review', 'proposed')
                    GROUP BY region_id
                ),
                country_parent AS (
                    SELECT DISTINCT ON (rel.from_region_id)
                        rel.from_region_id AS region_id,
                        parent.canonical_name AS parent_name
                    FROM wg_region_relationships rel
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    WHERE rel.status = 'accepted'
                      AND parent.kind = 'country'
                    ORDER BY rel.from_region_id, rel.confidence DESC, parent.canonical_name
                ),
                collapsible AS (
                    SELECT r.id
                    FROM wg_regions r
                    JOIN country_parent cp ON cp.region_id = r.id
                    LEFT JOIN owned o ON o.region_id = r.id
                    LEFT JOIN child_counts c ON c.region_id = r.id
                    LEFT JOIN candidates candidate_counts ON candidate_counts.region_id = r.id
                    WHERE r.kind IN (
                          'subregion',
                          'territory',
                          'unknown',
                          'cultural_region',
                          'diaspora_region',
                          'historical_region',
                          'language_region'
                      )
                      AND coalesce(r.raw_payload #>> '{region_accessibility,ui_visibility}', '') <> 'special_country_subregion'
                      AND (
                          (
                              coalesce(o.owned_count, 0)
                              + coalesce(candidate_counts.candidate_count, 0)
                              + coalesce(c.child_count, 0)
                          ) <= 1
                          OR (
                              coalesce(candidate_counts.candidate_count, 0) = 0
                              AND coalesce(o.owned_count, 0) < 2
                              AND coalesce(c.child_count, 0) < 3
                          )
                      )
                      AND coalesce(r.raw_payload #>> '{region_production_review,status}', '') NOT IN (
                          'approved_superregion',
                          'collapsed',
                          'rejected',
                          'demoted_source',
                          'hidden_from_ui'
                      )
                )
                UPDATE wg_regions r
                SET raw_payload = jsonb_set(
                        jsonb_set(
                            coalesce(r.raw_payload, '{}'::jsonb),
                            '{region_production_review}',
                            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                                || jsonb_build_object(
                                    'status', 'collapsed',
                                    'reason', 'low_value_subregion_merged_to_country',
                                    'reviewer_model', 'region-hierarchy-accessibility-v1'
                                ),
                            true
                        ),
                        '{region_accessibility}',
                        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', false,
                                'ui_visibility', 'collapsed',
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
                FROM collapsible
                WHERE collapsible.id = r.id
            """),
        )
        stats.low_value_regions_collapsed = int(collapsed.rowcount or 0)

        redundant_edges = await conn.execute(
            text("""
                WITH country_parented AS (
                    SELECT DISTINCT rel.from_region_id
                    FROM wg_region_relationships rel
                    JOIN wg_regions parent ON parent.id = rel.to_region_id
                    JOIN wg_regions child ON child.id = rel.from_region_id
                    WHERE rel.status = 'accepted'
                      AND parent.kind = 'country'
                      AND child.kind <> 'country'
                )
                UPDATE wg_region_relationships rel
                SET status = 'rejected',
                    review_reason = 'Rejected by full hierarchy pass: country parent is more specific.',
                    reviewer_model = 'region-hierarchy-accessibility-v1',
                    updated_at = now()
                FROM country_parented, wg_regions parent
                WHERE rel.from_region_id = country_parented.from_region_id
                  AND parent.id = rel.to_region_id
                  AND rel.status = 'accepted'
                  AND parent.kind IN ('continent', 'cultural_region', 'subregion')
                  AND parent.kind <> 'country'
                  AND parent.canonical_name <> 'United States'
            """)
        )
        stats.redundant_parent_edges_rejected = int(redundant_edges.rowcount or 0)

        accessibility = await conn.execute(
            text("""
                UPDATE wg_regions
                SET raw_payload = jsonb_set(
                        coalesce(raw_payload, '{}'::jsonb),
                        '{region_accessibility}',
                        coalesce(raw_payload #> '{region_accessibility}', '{}'::jsonb)
                            || jsonb_build_object(
                                'manual_access', kind = 'country',
                                'ui_visibility', CASE
                                    WHEN kind = 'country' THEN 'manual_country'
                                    WHEN coalesce(raw_payload #>> '{region_accessibility,ui_visibility}', '') = 'special_country_subregion'
                                    THEN 'special_country_subregion'
                                    WHEN coalesce(raw_payload #>> '{region_production_review,status}', '') = 'approved_superregion'
                                    THEN 'superregion_child_access'
                                    WHEN coalesce(raw_payload #>> '{region_production_review,status}', '') IN (
                                        'collapsed',
                                        'rejected',
                                        'demoted_source',
                                        'hidden_from_ui'
                                    )
                                    THEN coalesce(raw_payload #>> '{region_production_review,status}', 'hidden_from_ui')
                                    ELSE 'country_child'
                                END,
                                'reviewer_model', 'region-hierarchy-accessibility-v1'
                            ),
                        true
                    ),
                    updated_at = now()
            """)
        )
        stats.accessibility_rows_marked = int(accessibility.rowcount or 0)

        await conn.execute(
            text("""
                WITH hidden_regions AS (
                    SELECT
                        r.id AS region_id,
                        p.genre_id,
                        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) AS title
                    FROM wg_regions r
                    LEFT JOIN wg_region_promoted_genres p ON p.region_id = r.id
                    WHERE coalesce(r.raw_payload #>> '{region_production_review,status}', '') IN (
                        'collapsed',
                        'rejected',
                        'demoted_source',
                        'hidden_from_ui'
                    )
                ),
                hidden_genres AS (
                    SELECT coalesce(hidden_regions.genre_id, g.id) AS genre_id
                    FROM hidden_regions
                    LEFT JOIN wg_genres g ON lower(g.wikipedia_title) = lower(hidden_regions.title)
                    WHERE coalesce(hidden_regions.genre_id, g.id) IS NOT NULL
                )
                UPDATE wg_genres g
                SET is_non_genre = true,
                    non_genre_reviewed_at = now(),
                    non_genre_review_note = 'Hidden from UI by region-hierarchy-accessibility-v1.'
                FROM hidden_genres
                WHERE hidden_genres.genre_id = g.id
            """)
        )

        samples = (
            (
                await conn.execute(
                    text("""
                        SELECT canonical_name, kind,
                               raw_payload #>> '{region_production_review,status}' AS status,
                               raw_payload #>> '{region_accessibility,ui_visibility}' AS visibility
                        FROM wg_regions
                        WHERE raw_payload #>> '{region_accessibility,reviewer_model}'
                            = 'region-hierarchy-accessibility-v1'
                        ORDER BY kind, canonical_name
                        LIMIT :sample
                    """),
                    {"sample": sample_size},
                )
            )
            .mappings()
            .fetchall()
        )
        stats.sample = [
            f"{row['canonical_name']} ({row['kind']}): {row['visibility']} / {row['status'] or 'active'}"
            for row in samples
        ]

    logger.info(
        "region_hierarchy_accessibility_complete",
        regions_seen=stats.regions_seen,
        country_kind_updates=stats.country_kind_updates,
        territory_kind_updates=stats.territory_kind_updates,
        low_value_regions_collapsed=stats.low_value_regions_collapsed,
        dry_run=dry_run,
    )
    return stats
