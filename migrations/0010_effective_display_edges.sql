-- 0010_effective_display_edges.sql
--
-- Treat related_genre rows with displayable evidence_relation as active display
-- edges for traversal/index lookup purposes while preserving the stored
-- relation/evidence split.

begin;

drop index if exists wg_edges_active_display_idx;

create index if not exists wg_edges_active_display_idx
    on wg_edges(from_genre_id, relation, evidence_relation)
    where is_ignored = false
      and to_genre_id is not null
      and (
        relation in ('subgenre', 'derivative', 'fusion_genre')
        or (
          relation = 'related_genre'
          and evidence_relation in ('subgenre', 'derivative', 'fusion_genre')
        )
      );

commit;
