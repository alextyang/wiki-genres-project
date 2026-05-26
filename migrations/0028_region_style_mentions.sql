-- 0028_region_style_mentions.sql
--
-- Regional music pages often discuss a local treatment of broad global styles
-- such as pop, folk, classical, and electronic music. Keep that evidence, but
-- distinguish it from graph ownership so these rows do not become child edges.

begin;

alter table wg_region_genre_relationships
    drop constraint if exists wg_region_genre_relationships_relation_valid;

alter table wg_region_genre_relationships
    add constraint wg_region_genre_relationships_relation_valid check (relation in (
        'regional_scene',
        'local_scene',
        'traditional_region',
        'indigenous_region',
        'historical_region',
        'diaspora_region',
        'cultural_region',
        'regional_style_mention',
        'influence_or_context'
    ));

commit;
