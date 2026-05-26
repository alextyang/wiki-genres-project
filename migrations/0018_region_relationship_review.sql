-- 0018_region_relationship_review.sql
--
-- Phase 4 review metadata for staged regional relationships. Region-to-genre
-- staging already has status; this migration brings region-to-region staging
-- to the same reviewable shape and adds review annotations to both tables.

begin;

alter table wg_region_relationships
    add column if not exists status text not null default 'proposed',
    add column if not exists review_reason text,
    add column if not exists reviewer_model text,
    add column if not exists updated_at timestamptz not null default now();

alter table wg_region_relationships
    drop constraint if exists wg_region_relationships_status_valid;

alter table wg_region_relationships
    add constraint wg_region_relationships_status_valid check (status in (
        'proposed',
        'accepted',
        'rejected',
        'needs_review'
    ));

alter table wg_region_genre_relationships
    add column if not exists review_reason text,
    add column if not exists reviewer_model text;

create index if not exists wg_region_relationships_status_idx
    on wg_region_relationships(status, relation);

create index if not exists wg_region_genre_relationships_status_idx
    on wg_region_genre_relationships(status, relation);

commit;
