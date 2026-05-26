-- 0006_related_genre_relation.sql
--
-- Add a non-display relationship type for broad derived coverage. The explorer
-- intentionally ignores this relation, while API consumers can use it for
-- richer graph traversal and search.

begin;

alter table wg_edges
    drop constraint if exists wg_edges_relation_valid;

alter table wg_edges
    add constraint wg_edges_relation_valid check (relation in (
        'subgenre', 'derivative', 'stylistic_origin', 'cultural_origin',
        'fusion_genre', 'regional_scene', 'local_scene', 'other_name',
        'influenced_by', 'subclass_of', 'part_of', 'instance_of',
        'related_genre'
    ));

commit;
