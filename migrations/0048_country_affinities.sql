-- 0048_country_affinities.sql
--
-- Durable country interpretation cache for country-scoped cloud layouts.

begin;

create table if not exists wg_wikipedia_page_content_cache (
    wikipedia_title text primary key,
    wikitext text,
    upstream_revision bigint,
    content_sha256 text,
    fetch_status text not null default 'ok',
    last_fetched_at timestamptz not null default now(),
    raw_payload jsonb not null default '{}'::jsonb,
    constraint wg_wikipedia_page_content_cache_status_valid check (
        fetch_status in ('ok', 'missing', 'error')
    )
);

create index if not exists wg_wikipedia_page_content_cache_fetched_idx
    on wg_wikipedia_page_content_cache(last_fetched_at desc);

create table if not exists wg_genre_country_affinities (
    genre_id text not null references wg_genres(id) on delete cascade,
    region_id text not null references wg_regions(id) on delete cascade,
    score real not null,
    confidence real not null,
    source_distribution jsonb not null default '{}'::jsonb,
    evidence jsonb not null default '[]'::jsonb,
    review_status text not null default 'auto',
    indexed_at timestamptz not null default now(),
    primary key (genre_id, region_id),
    constraint wg_genre_country_affinities_score_valid check (score >= 0 and score <= 1),
    constraint wg_genre_country_affinities_confidence_valid check (confidence >= 0 and confidence <= 1),
    constraint wg_genre_country_affinities_review_status_valid check (
        review_status in ('auto', 'needs_review', 'accepted', 'rejected')
    )
);

create index if not exists wg_genre_country_affinities_region_score_idx
    on wg_genre_country_affinities(region_id, score desc, confidence desc);

create index if not exists wg_genre_country_affinities_genre_idx
    on wg_genre_country_affinities(genre_id);

commit;
