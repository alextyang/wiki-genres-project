-- 0047_cloud_display_layout_cache.sql
--
-- Compact draw-time cloud layout cache. The semantic layout tables remain
-- inspectable/indexable build artifacts; this table stores only the numeric
-- fields the API needs to serve cloud labels quickly.

begin;

create table if not exists wg_genre_cloud_display_nodes (
    layout_key          text not null,
    genre_id            text not null references wg_genres(id) on delete cascade,
    x                   real not null,
    y                   real not null,
    text_width          real not null,
    text_height         real not null,
    box_width           real not null,
    box_height          real not null,
    box_pad_x           real not null,
    box_pad_y           real not null,
    priority            real not null,
    lod_score           real not null,
    min_visible_scale   real not null,
    show_scale          real not null,
    hide_scale          real not null,
    lod_rank            integer not null,
    lod_tier            smallint not null,
    display_source      smallint not null default 1,
    indexed_at          timestamptz not null default now(),
    primary key (layout_key, genre_id),
    constraint wg_genre_cloud_display_nodes_source_valid check (display_source in (1, 2))
);

create index if not exists wg_genre_cloud_display_nodes_lod_idx
    on wg_genre_cloud_display_nodes(layout_key, lod_rank, lod_score desc);

create index if not exists wg_genre_cloud_display_nodes_view_idx
    on wg_genre_cloud_display_nodes(layout_key, x, y);

commit;
