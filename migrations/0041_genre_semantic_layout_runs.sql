-- 0041_genre_semantic_layout_runs.sql
--
-- Per-layout quality summaries. These make semantic cloud generation
-- inspectable before the API starts serving a newly materialized layout.

begin;

create table if not exists wg_genre_semantic_layout_runs (
    layout_key      text not null,
    layout_version  text not null,
    vector_version  text not null,
    edge_version    text not null,
    metrics         jsonb not null default '{}'::jsonb,
    sample          jsonb not null default '[]'::jsonb,
    indexed_at      timestamptz not null default now(),
    primary key (layout_key, layout_version)
);

commit;
