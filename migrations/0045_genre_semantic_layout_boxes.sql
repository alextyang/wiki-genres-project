-- 0045_genre_semantic_layout_boxes.sql
--
-- Store the packed scale-1 cloud label envelopes used by the radial layout.

begin;

alter table if exists wg_genre_semantic_layouts
    add column if not exists box_width double precision not null default 0,
    add column if not exists box_height double precision not null default 0,
    add column if not exists box_pad_x double precision not null default 0,
    add column if not exists box_pad_y double precision not null default 0;

create index if not exists wg_genre_semantic_layouts_box_view_idx
    on wg_genre_semantic_layouts(layout_key, x, y, box_width, box_height);

commit;
