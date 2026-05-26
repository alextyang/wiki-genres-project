-- 0011_page_link_crawl_fetch_source.sql
--
-- Source-page genre discovery is an operator-initiated crawl separate from the
-- seed bootstrap and weekly sync, so keep its fetch provenance explicit.

begin;

alter table wg_fetch_log
    drop constraint wg_fetch_log_via_valid,
    add constraint wg_fetch_log_via_valid check (via in (
        'bootstrap', 'sync_worker', 'scheduler', 'manual', 'page-link-crawl'
    ));

commit;
