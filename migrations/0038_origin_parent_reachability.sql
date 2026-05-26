-- 0038_origin_parent_reachability.sql
--
-- Allow Music-root reachability to index stylistic-origin parent traces without
-- making them normal display child relations.

begin;

alter table wg_music_reachable_parents
    drop constraint if exists wg_music_reachable_parent_relation_valid;

alter table wg_music_reachable_parents
    add constraint wg_music_reachable_parent_relation_valid check (
        parent_relation in (
            'music_root',
            'subgenre',
            'derivative',
            'fusion_genre',
            'origin_parent'
        )
    );

commit;
