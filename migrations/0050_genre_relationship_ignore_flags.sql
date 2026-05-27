-- 0050_genre_relationship_ignore_flags.sql
--
-- Let derived graph guards suppress reviewed canonical relationships without
-- deleting the reviewed source record.

alter table wg_genre_relationships
    add column if not exists is_ignored boolean not null default false,
    add column if not exists ignored_reason text,
    add column if not exists ignored_at timestamptz;

drop view if exists wg_relationship_neighbor_edges;
drop view if exists wg_relationship_traversal_edges;
drop view if exists wg_relationship_detail_edges;

create view wg_relationship_detail_edges as
with has_reviewed_relationships as (
    select exists (
        select 1
        from wg_genre_relationships
        where status = 'active'
    ) as has_rows
)
select
    r.from_genre_id,
    r.to_genre_id,
    coalesce(nullif(r.to_raw_label, ''), to_g.wikipedia_title) as to_raw_label,
    r.relationship_type as relation,
    r.source,
    r.ordinal,
    r.relationship_type as evidence_relation,
    false as is_ignored,
    r.confidence,
    r.evidence,
    r.review_run_id
from wg_genre_relationships r
left join wg_genres to_g on to_g.id = r.to_genre_id
where r.status = 'active'
  and r.is_ignored = false
union all
select
    e.from_genre_id,
    e.to_genre_id,
    e.to_raw_label,
    e.relation,
    e.source,
    e.ordinal,
    e.evidence_relation,
    e.is_ignored,
    null::text as confidence,
    null::text as evidence,
    null::text as review_run_id
from wg_edges e
where not (select has_rows from has_reviewed_relationships);

create view wg_relationship_traversal_edges as
with has_reviewed_relationships as (
    select exists (
        select 1
        from wg_genre_relationships
        where status = 'active'
    ) as has_rows
),
review_edges as (
    select
        case
            when r.relationship_type in ('broader_genres', 'fusion_components', 'source_genres')
                then r.to_genre_id
            else r.from_genre_id
        end as from_genre_id,
        case
            when r.relationship_type in ('broader_genres', 'fusion_components', 'source_genres')
                then r.from_genre_id
            else r.to_genre_id
        end as to_genre_id,
        case
            when r.relationship_type in ('broader_genres', 'fusion_components', 'source_genres')
                then from_g.wikipedia_title
            else coalesce(nullif(r.to_raw_label, ''), to_g.wikipedia_title)
        end as to_raw_label,
        r.relationship_type as relation,
        r.source,
        r.ordinal,
        r.relationship_type as evidence_relation,
        false as is_ignored,
        r.confidence,
        r.evidence,
        r.review_run_id
    from wg_genre_relationships r
    join wg_genres from_g on from_g.id = r.from_genre_id
    left join wg_genres to_g on to_g.id = r.to_genre_id
    where r.status = 'active'
      and r.to_genre_id is not null
      and r.is_ignored = false
      and r.relationship_type not in (
        'sibling_or_adjacent_genres',
        'influenced_by',
        'influences'
      )
)
select *
from review_edges
union all
select
    e.from_genre_id,
    e.to_genre_id,
    e.to_raw_label,
    e.relation,
    e.source,
    e.ordinal,
    e.evidence_relation,
    e.is_ignored,
    null::text as confidence,
    null::text as evidence,
    null::text as review_run_id
from wg_edges e
where not (select has_rows from has_reviewed_relationships);

create view wg_relationship_neighbor_edges as
with has_reviewed_relationships as (
    select exists (
        select 1
        from wg_genre_relationships
        where status = 'active'
    ) as has_rows
),
review_edges as (
    select
        r.from_genre_id,
        r.to_genre_id,
        coalesce(nullif(r.to_raw_label, ''), to_g.wikipedia_title) as to_raw_label,
        r.relationship_type as relation,
        r.source,
        r.ordinal,
        r.relationship_type as evidence_relation,
        false as is_ignored,
        r.confidence,
        r.evidence,
        r.review_run_id
    from wg_genre_relationships r
    left join wg_genres to_g on to_g.id = r.to_genre_id
    where r.status = 'active'
      and r.is_ignored = false
      and r.to_genre_id is not null
    union all
    select
        r.to_genre_id as from_genre_id,
        r.from_genre_id as to_genre_id,
        from_g.wikipedia_title as to_raw_label,
        r.relationship_type as relation,
        r.source,
        r.ordinal,
        r.relationship_type as evidence_relation,
        false as is_ignored,
        r.confidence,
        r.evidence,
        r.review_run_id
    from wg_genre_relationships r
    join wg_genres from_g on from_g.id = r.from_genre_id
    where r.status = 'active'
      and r.is_ignored = false
      and r.to_genre_id is not null
      and r.relationship_type = 'sibling_or_adjacent_genres'
)
select *
from review_edges
union all
select
    e.from_genre_id,
    e.to_genre_id,
    e.to_raw_label,
    e.relation,
    e.source,
    e.ordinal,
    e.evidence_relation,
    e.is_ignored,
    null::text as confidence,
    null::text as evidence,
    null::text as review_run_id
from wg_edges e
where not (select has_rows from has_reviewed_relationships);
