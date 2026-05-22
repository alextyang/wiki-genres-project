-- 0002_pageviews.sql
--
-- 1. Fix CHECK constraints that were missing sync-related values.
-- 2. Add monthly_views_p30 denormalized column to wg_genres.
-- 3. Add wg_pageviews history table.

begin;

-- wg_revisions.triggered_by was missing 'sync'.
alter table wg_revisions
    drop constraint wg_revisions_triggered_by_valid,
    add  constraint wg_revisions_triggered_by_valid check (triggered_by in (
        'bootstrap', 'sync', 'eventstream', 'sparql', 'reconciler', 'manual'
    ));

-- wg_snapshots.kind was missing 'sync'.
alter table wg_snapshots
    drop constraint wg_snapshots_kind_valid,
    add  constraint wg_snapshots_kind_valid check (kind in (
        'bootstrap', 'sync', 'dump_audit', 'reconciler'
    ));

-- wg_frontier.reason was missing 'sync_new' and 'sync_stale'.
alter table wg_frontier
    drop constraint wg_frontier_reason_valid,
    add  constraint wg_frontier_reason_valid check (reason in (
        'seed', 'sync_new', 'sync_stale', 'eventstream', 'wikilink',
        'sparql', 'reconciler', 'manual'
    ));

-- Denormalized last-complete-month view count; enables fast sort and filter.
alter table wg_genres add column monthly_views_p30 integer;

create index wg_genres_monthly_views_idx
    on wg_genres(monthly_views_p30 desc nulls last)
    where monthly_views_p30 is not null;

-- Monthly pageview history sourced from the Wikimedia pageviews API.
create table wg_pageviews (
    genre_id    text        not null references wg_genres(id) on delete cascade,
    year        integer     not null,
    month       integer     not null check (month between 1 and 12),
    views       integer     not null check (views >= 0),
    fetched_at  timestamptz not null default now(),
    primary key (genre_id, year, month)
);

create index wg_pageviews_genre_recent_idx
    on wg_pageviews(genre_id, year desc, month desc);

commit;
