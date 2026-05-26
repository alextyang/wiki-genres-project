-- 0031_city_region_visibility.sql
--
-- City scenes should not remain visible regional graph nodes unless they have
-- accepted owned genre children. Cities with no candidate genre links are
-- rejected; cities with candidates but no final accepted owned children are
-- retained as data but hidden from the UI.

begin;

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

with city_without_owned_children as (
    select
        r.id as region_id,
        p.genre_id,
        coalesce(nullif(btrim(r.wikipedia_title), ''), 'Music of ' || r.canonical_name) as title
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

commit;
