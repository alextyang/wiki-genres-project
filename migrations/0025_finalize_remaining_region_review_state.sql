-- 0025_finalize_remaining_region_review_state.sql
--
-- Final metadata cleanup after the remaining-region review pass.

begin;

update wg_regions
set kind = 'continent',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0025_finalize_remaining_region_review_state',
        'previous_kind', kind
    ),
    updated_at = now()
where id = 'region-americas'
  and kind <> 'continent';

commit;
