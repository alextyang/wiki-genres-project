-- 0026_promote_regions_to_genres.sql
--
-- Promote the reviewed regional music graph into the main genre graph after
-- page-level regional child-genre extraction and review have completed.

begin;

alter table wg_edges
    drop constraint if exists wg_edges_source_valid;

alter table wg_edges
    add constraint wg_edges_source_valid check (source in (
        'infobox', 'wikidata', 'inbound_index', 'manual_curation', 'region_promotion'
    ));

create table if not exists wg_region_promoted_genres (
    region_id       text primary key references wg_regions(id) on delete cascade,
    genre_id        text not null unique references wg_genres(id) on delete cascade,
    wikipedia_title text not null,
    promotion_rule  text not null,
    created_at      timestamptz not null default now()
);

with city_without_owned_children as (
    select
        r.id as region_id,
        p.genre_id,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title,
        exists (
            select 1
            from wg_region_genre_relationships rel
            where rel.region_id = r.id
        ) as has_genre_candidates
    from wg_regions r
    left join wg_region_promoted_genres p on p.region_id = r.id
    where r.kind = 'city'
      and not exists (
          select 1
          from wg_region_genre_relationships rel
          where rel.region_id = r.id
            and rel.status = 'accepted'
            and rel.relation not in ('regional_style_mention', 'influence_or_context')
      )
),
resolved_city_genres as (
    select
        city.region_id,
        city.has_genre_candidates,
        coalesce(city.genre_id, g.id) as genre_id
    from city_without_owned_children city
    left join wg_genres g on lower(g.wikipedia_title) = lower(city.title)
)
update wg_regions r
set raw_payload = jsonb_set(
        coalesce(r.raw_payload, '{}'::jsonb),
        '{region_production_review}',
        coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
            || jsonb_build_object(
                'status',
                case
                    when not city.has_genre_candidates then 'rejected'
                    else 'hidden_from_ui'
                end,
                'reason',
                case
                    when not city.has_genre_candidates
                    then 'city_without_genre_candidates_removed'
                    else 'city_without_final_genres_hidden'
                end,
                'reviewer_model',
                'city-region-visibility-v1'
            ),
        true
    ),
    updated_at = now()
from city_without_owned_children city
where city.region_id = r.id;

with city_with_owned_children as (
    select r.id as region_id
    from wg_regions r
    where r.kind = 'city'
      and exists (
          select 1
          from wg_region_genre_relationships rel
          where rel.region_id = r.id
            and rel.status = 'accepted'
            and rel.relation not in ('regional_style_mention', 'influence_or_context')
      )
)
update wg_regions r
set raw_payload = jsonb_set(
        jsonb_set(
            coalesce(r.raw_payload, '{}'::jsonb),
            '{region_production_review}',
            coalesce(r.raw_payload #> '{region_production_review}', '{}'::jsonb)
                || jsonb_build_object(
                    'status',
                    'approved_city_exception',
                    'reason',
                    'city_with_final_genres_visible',
                    'reviewer_model',
                    'city-region-visibility-v2'
                ),
            true
        ),
        '{region_accessibility}',
        coalesce(r.raw_payload #> '{region_accessibility}', '{}'::jsonb)
            || jsonb_build_object(
                'manual_access',
                false,
                'ui_visibility',
                'country_child',
                'reviewer_model',
                'city-region-visibility-v2'
            ),
        true
    ),
    updated_at = now()
from city_with_owned_children city
where city.region_id = r.id
  and coalesce(r.raw_payload #>> '{region_production_review,status}', '') in (
      '',
      'hidden_from_ui',
      'reviewed_empty',
      'rejected'
  );

with city_without_owned_children as (
    select
        r.id as region_id,
        p.genre_id,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title,
        exists (
            select 1
            from wg_region_genre_relationships rel
            where rel.region_id = r.id
        ) as has_genre_candidates
    from wg_regions r
    left join wg_region_promoted_genres p on p.region_id = r.id
    where r.kind = 'city'
      and not exists (
          select 1
          from wg_region_genre_relationships rel
          where rel.region_id = r.id
            and rel.status = 'accepted'
            and rel.relation not in ('regional_style_mention', 'influence_or_context')
      )
),
resolved_city_genres as (
    select distinct coalesce(city.genre_id, g.id) as genre_id
    from city_without_owned_children city
    left join wg_genres g on lower(g.wikipedia_title) = lower(city.title)
    where coalesce(city.genre_id, g.id) is not null
)
update wg_genres g
set is_non_genre = true,
    non_genre_reviewed_at = now(),
    non_genre_review_note = 'Hidden from UI by city-region-visibility-v1: city region has no accepted owned genre children.'
from resolved_city_genres hidden
where hidden.genre_id = g.id;

with hidden_regions as (
    select
        r.id as region_id,
        p.genre_id,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title
    from wg_regions r
    left join wg_region_promoted_genres p on p.region_id = r.id
    where coalesce(r.raw_payload #>> '{region_production_review,status}', '') in (
        'collapsed',
        'rejected',
        'demoted_source',
        'hidden_from_ui'
    )
),
hidden_genres as (
    select coalesce(hidden_regions.genre_id, g.id) as genre_id
    from hidden_regions
    left join wg_genres g on lower(g.wikipedia_title) = lower(hidden_regions.title)
    where coalesce(hidden_regions.genre_id, g.id) is not null
)
update wg_genres g
set is_non_genre = true,
    non_genre_reviewed_at = now(),
    non_genre_review_note = 'Hidden from UI by region production hierarchy rules.'
from hidden_genres hidden
where hidden.genre_id = g.id;

delete from wg_region_promoted_genres p
using wg_regions r
where p.region_id = r.id
  and r.kind = 'city'
  and not exists (
      select 1
      from wg_region_genre_relationships rel
      where rel.region_id = r.id
        and rel.status = 'accepted'
        and rel.relation not in ('regional_style_mention', 'influence_or_context')
  );

delete from wg_region_promoted_genres p
where not exists (
    select 1
    from wg_regions r
    where r.id = p.region_id
      and coalesce(r.raw_payload #>> '{region_production_review,status}', '') not in (
        'collapsed',
        'rejected',
        'demoted_source',
        'hidden_from_ui'
      )
      and not (
          r.kind = 'city'
          and not exists (
              select 1
              from wg_region_genre_relationships rel
              where rel.region_id = r.id
                and rel.status = 'accepted'
                and rel.relation not in ('regional_style_mention', 'influence_or_context')
          )
      )
      and (
        nullif(btrim(r.wikipedia_title), '') is not null
        or exists (
            select 1
            from wg_region_sources s
            where s.region_id = r.id
              and s.source_type = 'wikipedia_category'
        )
        or exists (
            select 1
            from wg_region_relationships rel
            where rel.status = 'accepted'
              and (rel.from_region_id = r.id or rel.to_region_id = r.id)
        )
        or exists (
            select 1
            from wg_region_genre_relationships rel
            where rel.status = 'accepted'
              and rel.region_id = r.id
        )
        or exists (
            select 1
            from wg_region_music_pages page
            where page.region_id = r.id
        )
      )
);

insert into wg_genres (
    id,
    wikidata_qid,
    wikipedia_title,
    wikipedia_url,
    summary,
    is_seed,
    has_infobox,
    is_non_genre,
    non_genre_reviewed_at,
    non_genre_review_note
)
with chosen as (
    select
        r.id as region_id,
        r.wikidata_qid,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title,
        case
            when nullif(btrim(r.wikipedia_title), '') is null then 'fallback_music_of_region'
            else 'reviewed_region_title'
        end as promotion_rule
    from wg_regions r
    where coalesce(r.raw_payload #>> '{region_production_review,status}', '') not in (
        'collapsed',
        'rejected',
        'demoted_source',
        'hidden_from_ui'
       )
       and not (
            r.kind = 'city'
            and not exists (
                select 1
                from wg_region_genre_relationships rel
                where rel.region_id = r.id
                  and rel.status = 'accepted'
                  and rel.relation not in ('regional_style_mention', 'influence_or_context')
            )
       )
       and (
            nullif(btrim(r.wikipedia_title), '') is not null
       or exists (
            select 1
            from wg_region_sources s
            where s.region_id = r.id
              and s.source_type = 'wikipedia_category'
       )
       or exists (
            select 1
            from wg_region_relationships rel
            where rel.status = 'accepted'
              and (rel.from_region_id = r.id or rel.to_region_id = r.id)
       )
       or exists (
            select 1
            from wg_region_genre_relationships rel
            where rel.status = 'accepted'
              and rel.region_id = r.id
       )
       or exists (
            select 1
            from wg_region_music_pages page
            where page.region_id = r.id
       )
       )
),
resolved as (
    select
        c.region_id,
        coalesce(g.id, 'wg-region-' || regexp_replace(c.region_id, '^region-', '')) as genre_id,
        coalesce(g.wikipedia_title, c.title) as title,
        case
            when g.id is not null and g.id not like 'wg-region-%' then 'existing_genre_title'
            else c.promotion_rule
        end as promotion_rule,
        c.wikidata_qid
    from chosen c
    left join wg_genres g on lower(g.wikipedia_title) = lower(c.title)
)
select
    genre_id,
    wikidata_qid,
    title,
    'https://en.wikipedia.org/wiki/' || replace(title, ' ', '_'),
    'Reviewed regional music node promoted into the genre graph.',
    false,
    false,
    false,
    now(),
    'Promoted from reviewed regional music graph in migration 0026.'
from resolved
where promotion_rule <> 'existing_genre_title'
on conflict (id) do nothing;

insert into wg_region_promoted_genres (
    region_id,
    genre_id,
    wikipedia_title,
    promotion_rule
)
with chosen as (
    select
        r.id as region_id,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title,
        case
            when nullif(btrim(r.wikipedia_title), '') is null then 'fallback_music_of_region'
            else 'reviewed_region_title'
        end as promotion_rule
    from wg_regions r
    where coalesce(r.raw_payload #>> '{region_production_review,status}', '') not in (
        'collapsed',
        'rejected',
        'demoted_source',
        'hidden_from_ui'
       )
       and not (
            r.kind = 'city'
            and not exists (
                select 1
                from wg_region_genre_relationships rel
                where rel.region_id = r.id
                  and rel.status = 'accepted'
                  and rel.relation not in ('regional_style_mention', 'influence_or_context')
            )
       )
       and (
            nullif(btrim(r.wikipedia_title), '') is not null
       or exists (
            select 1
            from wg_region_sources s
            where s.region_id = r.id
              and s.source_type = 'wikipedia_category'
       )
       or exists (
            select 1
            from wg_region_relationships rel
            where rel.status = 'accepted'
              and (rel.from_region_id = r.id or rel.to_region_id = r.id)
       )
       or exists (
            select 1
            from wg_region_genre_relationships rel
            where rel.status = 'accepted'
              and rel.region_id = r.id
       )
       or exists (
            select 1
            from wg_region_music_pages page
            where page.region_id = r.id
       )
       )
),
resolved as (
    select
        c.region_id,
        coalesce(g.id, 'wg-region-' || regexp_replace(c.region_id, '^region-', '')) as genre_id,
        coalesce(g.wikipedia_title, c.title) as title,
        case
            when g.id is not null and g.id not like 'wg-region-%' then 'existing_genre_title'
            else c.promotion_rule
        end as promotion_rule
    from chosen c
    left join wg_genres g on lower(g.wikipedia_title) = lower(c.title)
),
resolved_unique as (
    select distinct on (genre_id)
        region_id,
        genre_id,
        title,
        promotion_rule
    from resolved
    order by
        genre_id,
        case
            when exists (
                select 1
                from wg_region_promoted_genres existing
                where existing.region_id = resolved.region_id
                  and existing.genre_id = resolved.genre_id
            ) then 0
            else 1
        end,
        case
            when region_id like '%-music' then 0
            else 1
        end,
        region_id
)
select
    region_id,
    genre_id,
    title,
    promotion_rule
from resolved_unique
on conflict (region_id) do update
set genre_id = excluded.genre_id,
    wikipedia_title = excluded.wikipedia_title,
    promotion_rule = excluded.promotion_rule;

update wg_genres g
set is_non_genre = false,
    non_genre_reviewed_at = coalesce(g.non_genre_reviewed_at, now()),
    non_genre_review_note = coalesce(
        g.non_genre_review_note,
        'Approved regional music node promoted from reviewed regional graph in migration 0026.'
    )
from wg_region_promoted_genres p
where p.genre_id = g.id
  and g.is_non_genre = true;

insert into wg_region_music_pages (
    region_id,
    genre_id,
    role,
    source_type,
    source_title,
    evidence_text,
    confidence,
    raw_payload
)
select
    p.region_id,
    p.genre_id,
    'primary_music_page',
    'gpt_review',
    'Region graph promotion',
    'Reviewed regional node promoted to a genre graph row.',
    1.0,
    jsonb_build_object('promotion_migration', '0026_promote_regions_to_genres')
from wg_region_promoted_genres p
where not exists (
    select 1
    from wg_region_music_pages existing
    where existing.region_id = p.region_id
      and existing.genre_id = p.genre_id
);

delete from wg_edges
where source = 'region_promotion';

insert into wg_edges (
    from_genre_id,
    to_genre_id,
    to_raw_label,
    relation,
    source,
    ordinal,
    evidence_relation,
    first_seen_at
)
with promoted_region_edges as (
    select distinct on (
        parent.genre_id,
        child.genre_id
    )
        parent.genre_id as from_genre_id,
        child.genre_id as to_genre_id,
        child.wikipedia_title as to_raw_label,
        'subgenre' as relation,
        'region_promotion' as source,
        rel.relation as evidence_relation,
        rel.confidence,
        child.wikipedia_title as sort_title
    from wg_region_relationships rel
    join wg_region_promoted_genres child on child.region_id = rel.from_region_id
    join wg_region_promoted_genres parent on parent.region_id = rel.to_region_id
    where rel.status = 'accepted'
      and child.genre_id <> parent.genre_id
    order by
        parent.genre_id,
        child.genre_id,
        case rel.relation
            when 'admin_parent' then 0
            when 'part_of' then 1
            when 'cultural_region_of' then 2
            when 'historical_region_of' then 3
            when 'diaspora_region_of' then 4
            when 'language_region_of' then 5
            else 9
        end,
        rel.confidence desc,
        rel.id
),
promoted_region_genre_edges as (
    select distinct on (
        region.genre_id,
        rel.genre_id
    )
        region.genre_id as from_genre_id,
        rel.genre_id as to_genre_id,
        genre.wikipedia_title as to_raw_label,
        'subgenre' as relation,
        'region_promotion' as source,
        rel.relation as evidence_relation,
        rel.confidence,
        genre.wikipedia_title as sort_title
    from wg_region_genre_relationships rel
    join wg_region_promoted_genres region on region.region_id = rel.region_id
    join wg_genres genre on genre.id = rel.genre_id
    where rel.status = 'accepted'
      and rel.relation not in ('regional_style_mention', 'influence_or_context')
      and genre.deleted_at is null
      and genre.is_non_genre = false
      and region.genre_id <> rel.genre_id
    order by
        region.genre_id,
        rel.genre_id,
        case rel.relation
            when 'indigenous_region' then 0
            when 'traditional_region' then 1
            when 'historical_region' then 2
            when 'diaspora_region' then 3
            when 'cultural_region' then 4
            when 'regional_scene' then 5
            else 9
        end,
        rel.confidence desc,
        rel.id
),
all_promoted_edges as (
    select * from promoted_region_edges
    union all
    select * from promoted_region_genre_edges
),
deduped_promoted_edges as (
    select distinct on (
        from_genre_id,
        to_genre_id,
        relation,
        source
    )
        from_genre_id,
        to_genre_id,
        to_raw_label,
        relation,
        source,
        evidence_relation,
        sort_title
    from all_promoted_edges
    order by
        from_genre_id,
        to_genre_id,
        relation,
        source,
        case evidence_relation
            when 'indigenous_region' then 0
            when 'traditional_region' then 1
            when 'historical_region' then 2
            when 'diaspora_region' then 3
            when 'cultural_region' then 4
            when 'regional_scene' then 5
            when 'admin_parent' then 6
            when 'part_of' then 7
            else 9
        end,
        confidence desc,
        sort_title
),
numbered_edges as (
    select
        from_genre_id,
        to_genre_id,
        to_raw_label,
        relation,
        source,
        evidence_relation,
        row_number() over (
            partition by from_genre_id, relation, source
            order by sort_title, to_genre_id, evidence_relation
        ) - 1 as ordinal
    from deduped_promoted_edges
)
select
    from_genre_id,
    to_genre_id,
    to_raw_label,
    relation,
    source,
    ordinal,
    evidence_relation,
    now()
from numbered_edges;

insert into wg_snapshots (
    id,
    kind,
    started_at,
    finished_at,
    nodes_total,
    edges_total,
    notes
)
select
    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') || '-region-promotion',
    'reconciler',
    now(),
    now(),
    (select count(*) from wg_region_promoted_genres),
    (select count(*) from wg_edges where source = 'region_promotion'),
    'Promoted reviewed regional music graph nodes and accepted regional relationships into wg_genres and wg_edges.';

commit;
