-- 0008_ignore_cyclic_edges.sql
--
-- Keep circular display relationships auditable without rendering/traversing
-- them as genre children.

begin;

alter table wg_edges
    add column if not exists is_ignored boolean not null default false,
    add column if not exists ignored_reason text,
    add column if not exists ignored_at timestamptz;

create index if not exists wg_edges_active_display_idx
    on wg_edges(from_genre_id, relation)
    where is_ignored = false
      and to_genre_id is not null
      and relation in ('subgenre', 'derivative', 'fusion_genre');

commit;
