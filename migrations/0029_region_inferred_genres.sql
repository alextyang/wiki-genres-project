-- 0029_region_inferred_genres.sql
--
-- Stage inferred regional variant genre candidates without promoting them
-- into wg_genres/wg_edges until explicitly accepted.

begin;

create table if not exists wg_region_inferred_genres (
    id                    bigserial primary key,
    region_id             text not null references wg_regions(id) on delete cascade,
    base_genre_id         text not null references wg_genres(id) on delete cascade,
    candidate_kind        text not null,
    proposed_display_title text not null,
    wikipedia_title       text,
    source_title          text,
    source_section        text,
    confidence            double precision not null default 0.5,
    status                text not null default 'proposed',
    raw_payload           jsonb not null default '{}'::jsonb,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    constraint wg_region_inferred_genres_kind_valid check (candidate_kind in (
        'wikipedia_page',
        'section_inferred'
    )),
    constraint wg_region_inferred_genres_status_valid check (status in (
        'proposed',
        'accepted',
        'rejected',
        'needs_review'
    )),
    constraint wg_region_inferred_genres_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_region_inferred_genres_unique_idx
    on wg_region_inferred_genres(
        region_id,
        base_genre_id,
        candidate_kind,
        coalesce(wikipedia_title, ''),
        coalesce(source_title, ''),
        coalesce(source_section, '')
    );

create index if not exists wg_region_inferred_genres_region_idx
    on wg_region_inferred_genres(region_id, status);

create index if not exists wg_region_inferred_genres_base_idx
    on wg_region_inferred_genres(base_genre_id, status);

commit;

