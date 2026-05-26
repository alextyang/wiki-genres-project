-- 0012_manual_curation_edges.sql
--
-- Allow persistent, auditable display edges curated by project maintainers.
-- The rows themselves are reapplied by `wiki-genres curate-genres` so they can
-- be inserted after the crawl has created the referenced pages.

begin;

alter table wg_edges
    drop constraint if exists wg_edges_source_valid;

alter table wg_edges
    add constraint wg_edges_source_valid check (source in (
        'infobox', 'wikidata', 'inbound_index', 'manual_curation'
    ));

commit;
