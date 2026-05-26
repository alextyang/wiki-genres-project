-- 0044_pure_region_relationships.sql
--
-- Repeatable projection of the genre-node graph into pure region nodes and
-- region-to-region edges. This is derived data: rebuild it from wg_genres,
-- wg_edges, wg_region_music_pages, and wg_region_promoted_genres whenever the
-- source graph changes.

begin;

create table if not exists wg_region_node_mappings (
    id                  bigserial primary key,
    genre_id            text not null references wg_genres(id) on delete cascade,
    region_id           text not null references wg_regions(id) on delete cascade,
    mapping_type        text not null,
    source_title        text not null,
    source_is_non_genre boolean not null default false,
    confidence          double precision not null default 0.7,
    raw_payload         jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_region_node_mappings_type_valid check (mapping_type in (
        'region_music_page',
        'region_promoted_genre',
        'title_music_of',
        'title_music_in',
        'category_music_of',
        'category_music_in',
        'category_region_music'
    )),
    constraint wg_region_node_mappings_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_region_node_mappings_unique_idx
    on wg_region_node_mappings(genre_id, region_id, mapping_type);

create index if not exists wg_region_node_mappings_genre_idx
    on wg_region_node_mappings(genre_id);

create index if not exists wg_region_node_mappings_region_idx
    on wg_region_node_mappings(region_id);

create table if not exists wg_pure_region_relationships (
    id                       bigserial primary key,
    from_region_id           text not null references wg_regions(id) on delete cascade,
    to_region_id             text not null references wg_regions(id) on delete cascade,
    relation                 text not null,
    source_from_genre_id     text not null references wg_genres(id) on delete cascade,
    source_to_genre_id       text not null references wg_genres(id) on delete cascade,
    source_edge_relation     text not null,
    source_edge_evidence     text,
    source_edge_source       text not null,
    source_direction         text not null default 'forward',
    confidence               double precision not null default 0.7,
    raw_payload              jsonb not null default '{}'::jsonb,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now(),
    constraint wg_pure_region_relationships_not_self check (
        from_region_id <> to_region_id
    ),
    constraint wg_pure_region_relationships_relation_valid check (relation in (
        'part_of',
        'admin_parent',
        'overlaps',
        'cultural_region_of',
        'diaspora_region_of',
        'historical_region_of',
        'language_region_of',
        'parallel_parent'
    )),
    constraint wg_pure_region_relationships_direction_valid check (
        source_direction in ('forward', 'inverted')
    ),
    constraint wg_pure_region_relationships_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_pure_region_relationships_unique_idx
    on wg_pure_region_relationships(
        from_region_id,
        to_region_id,
        relation,
        source_from_genre_id,
        source_to_genre_id,
        source_edge_relation,
        coalesce(source_edge_evidence, ''),
        source_edge_source,
        source_direction
    );

create index if not exists wg_pure_region_relationships_from_idx
    on wg_pure_region_relationships(from_region_id, relation);

create index if not exists wg_pure_region_relationships_to_idx
    on wg_pure_region_relationships(to_region_id, relation);

create index if not exists wg_pure_region_relationships_source_edge_idx
    on wg_pure_region_relationships(source_edge_relation, source_edge_source);

commit;
