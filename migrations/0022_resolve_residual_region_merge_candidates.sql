-- 0022_resolve_residual_region_merge_candidates.sql
--
-- Resolve residual deterministic region similarity candidates after the first
-- GPT region review cleanup.

begin;

-- These same-name pairs are distinct region scopes, not duplicates.
update wg_region_merge_candidates
set status = 'do_not_merge',
    review_reason = 'Review resolution 0022: distinct city/province, city/state, or country/state scopes.',
    reviewer_model = 'manual',
    updated_at = now()
where (left_region_id, right_region_id) in (
    ('region-bremen-city', 'region-bremen-state'),
    ('region-groningen-city', 'region-groningen-province'),
    ('region-utrecht-city', 'region-utrecht-province'),
    ('region-georgia', 'region-georgia-u-s-state')
);

-- Tighten kinds for the remaining reviewed same-name scopes.
update wg_regions
set kind = 'subregion',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0022_resolve_residual_region_merge_candidates',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-bremen-state',
    'region-groningen-province',
    'region-utrecht-province',
    'region-georgia-u-s-state'
)
  and kind <> 'subregion';

update wg_regions
set kind = 'country',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0022_resolve_residual_region_merge_candidates',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-georgia',
    'region-indonesia'
)
  and kind <> 'country';

-- "Indonesian" and "Indonesian regional" are category containers, not
-- displayable regions. Bali and Sumatra already retain accepted direct
-- Indonesia parent edges from Category:Music of Indonesia by province.
delete from wg_regions
where id in (
    'region-indonesian',
    'region-indonesian-regional'
);

commit;
