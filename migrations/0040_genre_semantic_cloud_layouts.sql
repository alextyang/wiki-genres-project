-- 0040_genre_semantic_cloud_layouts.sql
--
-- Rebuildable purpose-built cloud placement data. This is intentionally
-- separate from the color index: cloud placement uses its own semantic text,
-- relationship, playlist, and region signals.

begin;

create table if not exists wg_genre_semantic_vectors (
    layout_key      text not null,
    genre_id        text not null references wg_genres(id) on delete cascade,
    document_text   text not null,
    terms           jsonb not null default '{}'::jsonb,
    vector          jsonb not null default '{}'::jsonb,
    metadata        jsonb not null default '{}'::jsonb,
    vector_version  text not null,
    indexed_at      timestamptz not null default now(),
    primary key (layout_key, genre_id)
);

create index if not exists wg_genre_semantic_vectors_genre_idx
    on wg_genre_semantic_vectors(genre_id);

create table if not exists wg_genre_semantic_edges (
    layout_key       text not null,
    from_genre_id    text not null references wg_genres(id) on delete cascade,
    to_genre_id      text not null references wg_genres(id) on delete cascade,
    weight           double precision not null check (weight > 0),
    sources          jsonb not null default '{}'::jsonb,
    edge_version     text not null,
    indexed_at       timestamptz not null default now(),
    primary key (layout_key, from_genre_id, to_genre_id)
);

create index if not exists wg_genre_semantic_edges_from_idx
    on wg_genre_semantic_edges(layout_key, from_genre_id);

create index if not exists wg_genre_semantic_edges_to_idx
    on wg_genre_semantic_edges(layout_key, to_genre_id);

create table if not exists wg_genre_semantic_layouts (
    layout_key       text not null,
    genre_id         text not null references wg_genres(id) on delete cascade,
    x                double precision not null,
    y                double precision not null,
    width            double precision not null,
    height           double precision not null,
    priority         double precision not null,
    is_center        boolean not null default false,
    metadata         jsonb not null default '{}'::jsonb,
    layout_version   text not null,
    indexed_at       timestamptz not null default now(),
    primary key (layout_key, genre_id)
);

create index if not exists wg_genre_semantic_layouts_view_idx
    on wg_genre_semantic_layouts(layout_key, x, y);

create index if not exists wg_genre_semantic_layouts_priority_idx
    on wg_genre_semantic_layouts(layout_key, priority desc);

commit;
