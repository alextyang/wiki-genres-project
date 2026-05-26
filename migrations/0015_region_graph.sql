-- 0015_region_graph.sql
--
-- Region graph substrate for comprehensive regional music coverage. This is
-- intentionally separate from wg_edges so crawler/GPT evidence can be merged,
-- reviewed, and promoted without flattening all regions into genre edges.

begin;

create table if not exists wg_regions (
    id              text primary key,
    canonical_name  text not null,
    kind            text not null default 'unknown',
    display_title   text,
    wikidata_qid    text,
    wikipedia_title text,
    confidence      double precision not null default 0.5,
    raw_payload     jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint wg_regions_id_nonempty check (length(btrim(id)) > 0),
    constraint wg_regions_name_nonempty check (length(btrim(canonical_name)) > 0),
    constraint wg_regions_kind_valid check (kind in (
        'country',
        'territory',
        'city',
        'subregion',
        'continent',
        'cultural_region',
        'diaspora_region',
        'historical_region',
        'language_region',
        'unknown'
    )),
    constraint wg_regions_confidence_valid check (confidence >= 0 and confidence <= 1)
);

create unique index if not exists wg_regions_canonical_name_lower_idx
    on wg_regions(lower(canonical_name));

create index if not exists wg_regions_kind_idx
    on wg_regions(kind);

create table if not exists wg_region_sources (
    id              bigserial primary key,
    region_id       text references wg_regions(id) on delete cascade,
    source_type     text not null,
    source_url      text,
    source_title    text,
    source_section  text,
    evidence_text   text,
    extractor_model text,
    confidence      double precision not null default 0.5,
    raw_payload     jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    constraint wg_region_sources_type_valid check (source_type in (
        'approved_music_page',
        'wikipedia_article',
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_sources_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_region_sources_unique_idx
    on wg_region_sources(
        coalesce(region_id, ''),
        source_type,
        coalesce(source_url, ''),
        coalesce(source_title, ''),
        coalesce(source_section, '')
    );

create table if not exists wg_region_relationships (
    id              bigserial primary key,
    from_region_id  text not null references wg_regions(id) on delete cascade,
    to_region_id    text not null references wg_regions(id) on delete cascade,
    relation        text not null,
    source_id       bigint references wg_region_sources(id) on delete set null,
    source_type     text not null,
    source_url      text,
    source_title    text,
    source_section  text,
    evidence_text   text,
    confidence      double precision not null default 0.5,
    raw_payload     jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    constraint wg_region_relationships_not_self check (from_region_id <> to_region_id),
    constraint wg_region_relationships_relation_valid check (relation in (
        'part_of',
        'admin_parent',
        'overlaps',
        'cultural_region_of',
        'diaspora_region_of',
        'historical_region_of',
        'language_region_of',
        'parallel_parent'
    )),
    constraint wg_region_relationships_source_type_valid check (source_type in (
        'approved_music_page',
        'wikipedia_article',
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_relationships_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create unique index if not exists wg_region_relationships_unique_idx
    on wg_region_relationships(
        from_region_id,
        to_region_id,
        relation,
        source_type,
        coalesce(source_url, ''),
        coalesce(source_title, ''),
        coalesce(source_section, '')
    );

create index if not exists wg_region_relationships_from_idx
    on wg_region_relationships(from_region_id, relation);

create index if not exists wg_region_relationships_to_idx
    on wg_region_relationships(to_region_id, relation);

create table if not exists wg_region_music_pages (
    region_id       text not null references wg_regions(id) on delete cascade,
    genre_id        text not null references wg_genres(id) on delete cascade,
    role            text not null default 'primary_music_page',
    source_id       bigint references wg_region_sources(id) on delete set null,
    source_type     text not null,
    source_url      text,
    source_title    text,
    evidence_text   text,
    confidence      double precision not null default 0.8,
    raw_payload     jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    primary key (region_id, genre_id, role, source_type),
    constraint wg_region_music_pages_role_valid check (role in (
        'primary_music_page',
        'category_proxy',
        'list_proxy',
        'article_context'
    )),
    constraint wg_region_music_pages_source_type_valid check (source_type in (
        'approved_music_page',
        'wikipedia_article',
        'wikipedia_category',
        'wikipedia_list',
        'wikipedia_navbox',
        'wikidata',
        'manual',
        'gpt_review'
    )),
    constraint wg_region_music_pages_confidence_valid check (
        confidence >= 0 and confidence <= 1
    )
);

create index if not exists wg_region_music_pages_genre_idx
    on wg_region_music_pages(genre_id);

commit;
