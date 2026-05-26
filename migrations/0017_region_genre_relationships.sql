-- 0017_region_genre_relationships.sql
--
-- Phase 3 staging edges from reviewed regional evidence to existing approved
-- genre rows. These are intentionally separate from wg_edges so regional
-- coverage can be reviewed without changing the explorer's display graph.

begin;

create table if not exists wg_region_genre_relationships (
    id              bigserial primary key,
    region_id       text not null references wg_regions(id) on delete cascade,
    genre_id        text not null references wg_genres(id) on delete cascade,
    relation        text not null,
    source_id       bigint references wg_region_sources(id) on delete set null,
    source_type     text not null,
    source_url      text,
    source_title    text,
    source_section  text,
    evidence_text   text,
    confidence      double precision not null default 0.5,
    status          text not null default 'proposed',
    raw_payload     jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint wg_region_genre_relationships_relation_valid check (relation in (
        'regional_scene',
        'local_scene',
        'traditional_region',
        'indigenous_region',
        'historical_region',
        'diaspora_region',
        'cultural_region'
    )),
    constraint wg_region_genre_relationships_source_type_valid check (source_type in (
        'approved_music_page',
        'wikipedia_article',
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_genre_relationships_status_valid check (status in (
        'proposed',
        'accepted',
        'rejected',
        'needs_review'
    )),
    constraint wg_region_genre_relationships_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_region_genre_relationships_unique_idx
    on wg_region_genre_relationships(
        region_id,
        genre_id,
        relation,
        source_type,
        coalesce(source_url, ''),
        coalesce(source_title, ''),
        coalesce(source_section, '')
    );

create index if not exists wg_region_genre_relationships_region_idx
    on wg_region_genre_relationships(region_id, relation);

create index if not exists wg_region_genre_relationships_genre_idx
    on wg_region_genre_relationships(genre_id, relation);

commit;
