-- 0042_genre_semantic_layout_lod.sql
--
-- Materialize stable level-of-detail scores for cloud labels.

begin;

alter table if exists wg_genre_semantic_layouts
    add column if not exists lod_score double precision not null default 0.0,
    add column if not exists min_visible_scale double precision not null default 2.0,
    add column if not exists show_scale double precision not null default 2.0,
    add column if not exists hide_scale double precision not null default 1.85,
    add column if not exists lod_rank integer not null default 0,
    add column if not exists lod_tier integer not null default 5;

create index if not exists wg_genre_semantic_layouts_lod_idx
    on wg_genre_semantic_layouts(layout_key, lod_rank, lod_score desc);

commit;
