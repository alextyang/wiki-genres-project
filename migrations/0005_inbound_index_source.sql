-- 0005_inbound_index_source.sql
--
-- Allow derived, auditable parent -> child edges produced by the inbound
-- relationship indexer. These are separate from upstream infobox/Wikidata
-- facts so callers can distinguish inferred coverage from direct source data.

begin;

alter table wg_edges
    drop constraint if exists wg_edges_source_valid;

alter table wg_edges
    add constraint wg_edges_source_valid check (source in (
        'infobox', 'wikidata', 'inbound_index'
    ));

commit;
