-- 0013_genre_similarity_colors.sql
--
-- Rebuildable root-affinity colors for the explorer. These are derived from
-- the active display relationship graph, so they live outside wg_genres.

begin;

create table if not exists wg_genre_colors (
    genre_id       text primary key references wg_genres(id) on delete cascade,
    color_hex      text not null,
    confidence     double precision not null,
    root_affinity  jsonb not null default '{}'::jsonb,
    basis_version  text not null,
    indexed_at     timestamptz not null default now(),
    constraint wg_genre_colors_hex check (color_hex ~ '^#[0-9A-Fa-f]{6}$'),
    constraint wg_genre_colors_confidence check (confidence >= 0 and confidence <= 1)
);

create index if not exists wg_genre_colors_confidence_idx
    on wg_genre_colors(confidence desc);

commit;
