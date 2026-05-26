-- 0043_genre_semantic_layout_lod_score.sql
--
-- Backfill-compatible addition for stable progressive cloud LOD scoring.

begin;

alter table if exists wg_genre_semantic_layouts
    add column if not exists lod_score double precision not null default 0.0;

create index if not exists wg_genre_semantic_layouts_lod_score_idx
    on wg_genre_semantic_layouts(layout_key, lod_rank, lod_score desc);

commit;
