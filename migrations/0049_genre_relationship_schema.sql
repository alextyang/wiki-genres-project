-- 0049_genre_relationship_schema.sql
--
-- Canonical reviewed genre relationships.  `wg_edges` remains the raw/source
-- edge table; these tables and views become the application-facing contract for
-- reviewed relationship intent.

create table if not exists wg_genre_relationships (
    id                  bigserial primary key,
    from_genre_id       text not null references wg_genres(id) on delete cascade,
    to_genre_id         text references wg_genres(id) on delete cascade,
    to_raw_label        text not null,
    relationship_type   text not null,
    source              text not null default 'gpt_review',
    ordinal             integer not null default 0,
    confidence          text,
    evidence            text,
    justification       text,
    review_run_id       text,
    status              text not null default 'active',
    is_ignored          boolean not null default false,
    ignored_reason      text,
    ignored_at          timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_genre_relationships_type_valid check (relationship_type in (
        'broader_genres',
        'subgenres',
        'source_genres',
        'derived_genres',
        'fusion_components',
        'fusion_descendants',
        'regional_variations',
        'sibling_or_adjacent_genres',
        'influenced_by',
        'influences'
    )),
    constraint wg_genre_relationships_status_valid check (status in (
        'active',
        'rejected',
        'needs_human_review',
        'superseded'
    )),
    constraint wg_genre_relationships_not_self check (
        to_genre_id is null or from_genre_id <> to_genre_id
    )
);

create unique index if not exists wg_genre_relationships_active_unique_idx
    on wg_genre_relationships(from_genre_id, to_genre_id, relationship_type, source)
    where status = 'active' and to_genre_id is not null;

create index if not exists wg_genre_relationships_from_idx
    on wg_genre_relationships(from_genre_id, relationship_type)
    where status = 'active';

create index if not exists wg_genre_relationships_to_idx
    on wg_genre_relationships(to_genre_id, relationship_type)
    where status = 'active' and to_genre_id is not null;

create table if not exists wg_missing_genre_relationship_targets (
    id                  bigserial primary key,
    from_genre_id       text not null references wg_genres(id) on delete cascade,
    target_label        text not null,
    relationship_type   text not null,
    target_action       text,
    confidence          text,
    evidence            text,
    justification       text,
    review_run_id       text,
    status              text not null default 'pending',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_missing_genre_relationship_targets_type_valid check (relationship_type in (
        'broader_genres',
        'subgenres',
        'source_genres',
        'derived_genres',
        'fusion_components',
        'fusion_descendants',
        'regional_variations',
        'sibling_or_adjacent_genres',
        'influenced_by',
        'influences'
    )),
    constraint wg_missing_genre_relationship_targets_status_valid check (status in (
        'pending',
        'created',
        'mapped',
        'rejected',
        'needs_human_review'
    ))
);

create index if not exists wg_missing_genre_relationship_targets_from_idx
    on wg_missing_genre_relationship_targets(from_genre_id, relationship_type, status);

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
