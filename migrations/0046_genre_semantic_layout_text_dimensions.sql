-- 0046_genre_semantic_layout_text_dimensions.sql
-- Store precomputed text dimensions separately from padded collision boxes so
-- packing, streaming, hit testing, and underlines share the same label size.

alter table if exists wg_genre_semantic_layouts
    add column if not exists text_width double precision not null default 0,
    add column if not exists text_height double precision not null default 0;

create index if not exists wg_genre_semantic_layouts_text_box_idx
    on wg_genre_semantic_layouts(layout_key, text_width, text_height);
