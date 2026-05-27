-- 0051_review_relationship_reachability_constraint.sql
--
-- Music-root reachability now indexes application-facing reviewed relationship
-- labels from wg_relationship_traversal_edges.

alter table wg_music_reachable_parents
    drop constraint if exists wg_music_reachable_parent_relation_valid;

alter table wg_music_reachable_parents
    add constraint wg_music_reachable_parent_relation_valid check (
        parent_relation in (
            'music_root',
            'subgenre',
            'derivative',
            'fusion_genre',
            'origin_parent',
            'broader_genres',
            'subgenres',
            'derived_genres',
            'fusion_components',
            'fusion_descendants',
            'regional_variations'
        )
    );
