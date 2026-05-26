-- 0016_region_discovery_candidates.sql
--
-- Phase 2 discovery substrate: source pages and candidate nodes discovered from
-- Wikipedia categories, list pages, article/navbox scans, Wikidata, and later
-- GPT review workers.

begin;

create table if not exists wg_region_discovery_sources (
    source_key      text primary key,
    source_type     text not null,
    source_title    text not null,
    source_url      text,
    parent_key      text references wg_region_discovery_sources(source_key)
                    on delete set null,
    depth           integer not null default 0,
    status          text not null default 'pending',
    discovered_at   timestamptz not null default now(),
    last_fetched_at timestamptz,
    raw_payload     jsonb not null default '{}'::jsonb,
    constraint wg_region_discovery_sources_key_nonempty
        check (length(btrim(source_key)) > 0),
    constraint wg_region_discovery_sources_title_nonempty
        check (length(btrim(source_title)) > 0),
    constraint wg_region_discovery_sources_depth_nonnegative
        check (depth >= 0),
    constraint wg_region_discovery_sources_type_valid check (source_type in (
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_article',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_discovery_sources_status_valid check (status in (
        'pending',
        'fetched',
        'failed',
        'skipped'
    ))
);

create index if not exists wg_region_discovery_sources_status_idx
    on wg_region_discovery_sources(status, source_type, depth);

create index if not exists wg_region_discovery_sources_parent_idx
    on wg_region_discovery_sources(parent_key);

create table if not exists wg_region_candidates (
    candidate_key       text primary key,
    candidate_type      text not null,
    title               text not null,
    normalized_title    text not null,
    suggested_region_id text,
    suggested_region_name text,
    source_key          text references wg_region_discovery_sources(source_key)
                        on delete set null,
    source_type         text not null,
    source_title        text not null,
    source_url          text,
    source_section      text,
    evidence_text       text,
    confidence          double precision not null default 0.5,
    status              text not null default 'discovered',
    review_reason       text,
    extractor_model     text,
    raw_payload         jsonb not null default '{}'::jsonb,
    discovered_at       timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_region_candidates_key_nonempty
        check (length(btrim(candidate_key)) > 0),
    constraint wg_region_candidates_title_nonempty
        check (length(btrim(title)) > 0),
    constraint wg_region_candidates_confidence_valid
        check (confidence >= 0 and confidence <= 1),
    constraint wg_region_candidates_type_valid check (candidate_type in (
        'music_region_page',
        'music_region_category',
        'region_container_category',
        'regional_music_list',
        'regional_genre_page',
        'traditional_music_page',
        'indigenous_music_page',
        'historical_music_page',
        'cultural_region_page',
        'diaspora_region_page',
        'unknown_music_candidate'
    )),
    constraint wg_region_candidates_source_type_valid check (source_type in (
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_article',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_candidates_status_valid check (status in (
        'discovered',
        'already_in_graph',
        'queued_for_crawl',
        'needs_gpt_review',
        'accepted',
        'rejected'
    ))
);

create index if not exists wg_region_candidates_type_idx
    on wg_region_candidates(candidate_type, status);

create index if not exists wg_region_candidates_normalized_title_idx
    on wg_region_candidates(normalized_title);

create index if not exists wg_region_candidates_region_idx
    on wg_region_candidates(suggested_region_id);

create table if not exists wg_region_candidate_relationships (
    relationship_key text primary key,
    from_candidate_key text not null references wg_region_candidates(candidate_key)
                       on delete cascade,
    to_candidate_key   text not null references wg_region_candidates(candidate_key)
                       on delete cascade,
    relation           text not null,
    source_key         text references wg_region_discovery_sources(source_key)
                       on delete set null,
    source_type        text not null,
    source_title       text not null,
    source_section     text,
    evidence_text      text,
    confidence         double precision not null default 0.5,
    status             text not null default 'discovered',
    raw_payload        jsonb not null default '{}'::jsonb,
    discovered_at      timestamptz not null default now(),
    constraint wg_region_candidate_relationships_not_self
        check (from_candidate_key <> to_candidate_key),
    constraint wg_region_candidate_relationships_confidence_valid
        check (confidence >= 0 and confidence <= 1),
    constraint wg_region_candidate_relationships_relation_valid check (relation in (
        'source_contains',
        'list_section_contains',
        'category_contains',
        'possible_part_of',
        'possible_parallel_parent'
    )),
    constraint wg_region_candidate_relationships_source_type_valid check (source_type in (
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_article',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_candidate_relationships_status_valid check (status in (
        'discovered',
        'needs_gpt_review',
        'accepted',
        'rejected'
    ))
);

create index if not exists wg_region_candidate_relationships_from_idx
    on wg_region_candidate_relationships(from_candidate_key, relation);

create index if not exists wg_region_candidate_relationships_to_idx
    on wg_region_candidate_relationships(to_candidate_key, relation);

commit;
