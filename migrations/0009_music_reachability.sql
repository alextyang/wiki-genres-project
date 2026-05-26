-- 0009_music_reachability.sql
--
-- Materialized Music-root reachability for display parents. This lets the UI
-- ask which parents of a selected genre can be progressively revealed from the
-- synthetic Music root, and how far each parent sits from Music.

begin;

create table if not exists wg_music_reachable_parents (
    genre_id                 text not null references wg_genres(id) on delete cascade,
    parent_genre_id          text not null,
    root_genre_id            text not null references wg_genres(id) on delete cascade,
    parent_relation          text not null,
    parent_source            text not null,
    parent_ordinal           integer not null,
    parent_depth_from_music  integer not null check (parent_depth_from_music >= 0),
    depth_from_music         integer not null check (depth_from_music >= 1),
    path_genre_ids           text[] not null,
    indexed_at               timestamptz not null default now(),
    primary key (
        genre_id,
        parent_genre_id,
        parent_relation,
        parent_source,
        parent_ordinal
    ),
    constraint wg_music_reachable_parent_relation_valid check (
        parent_relation in ('music_root', 'subgenre', 'derivative', 'fusion_genre')
    )
);

create index if not exists wg_music_reachable_parents_parent_idx
    on wg_music_reachable_parents(parent_genre_id);

create index if not exists wg_music_reachable_parents_depth_idx
    on wg_music_reachable_parents(depth_from_music);

commit;
