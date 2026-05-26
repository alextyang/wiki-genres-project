-- 0021_resolve_region_review_findings.sql
--
-- Apply the first GPT-assisted region graph review findings. This migration
-- resolves only staged regional graph issues: artifact/work nodes, duplicate
-- region nodes, bad containment edges, kind mismatches, and overly broad
-- region-to-genre attachments.

begin;

-- Mark reviewed findings as accepted before any node deletes null out FKs.
update wg_region_tree_review_findings
set status = 'accepted',
    updated_at = now()
where status = 'needs_review'
  and finding_type in (
      'bad_region_node',
      'duplicate_region',
      'kind_mismatch',
      'wrong_region_direction',
      'wrong_region_genre',
      'wrong_region_parent'
  );

-- Retag misclassified country / country-like roots found by review.
update wg_regions
set kind = 'country',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0021_resolve_region_review_findings',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-australia',
    'region-bangladesh',
    'region-canada',
    'region-england',
    'region-germany',
    'region-greece',
    'region-india',
    'region-ireland',
    'region-italy',
    'region-nepal',
    'region-netherlands',
    'region-pakistan',
    'region-serbia',
    'region-spain',
    'region-switzerland',
    'region-united-states'
)
  and kind <> 'country';

-- Rhodesia is historical context for Zimbabwe, not a modern subregion.
update wg_regions
set kind = 'historical_region',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0021_resolve_region_review_findings',
        'previous_kind', kind
    ),
    updated_at = now()
where id = 'region-rhodesia'
  and kind <> 'historical_region';

update wg_region_relationships
set relation = 'historical_region_of',
    review_reason = 'Review resolution 0021: Rhodesia is historical context for Zimbabwe, not part_of containment.',
    reviewer_model = 'gpt-5.4-mini',
    updated_at = now()
where from_region_id = 'region-rhodesia'
  and to_region_id = 'region-zimbabwe'
  and relation = 'part_of'
  and status = 'accepted';

-- Reject bad containment/direction edges without deleting evidence.
update wg_region_relationships
set status = 'rejected',
    review_reason = 'Review resolution 0021: rejected GPT-reviewed bad regional containment/direction edge.',
    reviewer_model = 'gpt-5.4-mini',
    updated_at = now()
where status = 'accepted'
  and (
      (from_region_id = 'region-comoros' and to_region_id = 'region-mayotte')
      or (from_region_id = 'region-inner-mongolia' and to_region_id = 'region-central-asia')
      or (from_region_id = 'region-mid-atlantic-united-states' and to_region_id = 'region-virginia')
      or (from_region_id = 'region-samoa' and to_region_id = 'region-american-samoa')
      or (from_region_id = 'region-virgin-islands' and to_region_id = 'region-british-virgin-islands')
      or (from_region_id = 'region-zimbabwe' and to_region_id = 'region-east-africa')
      or (from_region_id = 'region-southern-china' and to_region_id = 'region-guangdong')
  );

-- Reject broad region-genre attachments where a specific region already owns
-- the same genre and broader regions can inherit upward.
update wg_region_genre_relationships
set status = 'rejected',
    review_reason = 'Review resolution 0021: rejected over-broad regional genre attachment, keep specific region edge and inherit upward.',
    reviewer_model = 'gpt-5.4-mini',
    updated_at = now()
where status = 'accepted'
  and (
      (region_id = 'region-latin-america' and genre_id = 'wg-q40461')
      or (region_id = 'region-southern-united-states' and genre_id = 'wg-q1026089')
      or (region_id = 'region-oceania' and genre_id = 'wg-q1892019')
  );

-- Merge Region of Murcia duplicate evidence into the autonomous-community node.
insert into wg_region_sources (
    region_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload,
    created_at
)
select
    'region-region-of-murcia',
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-murcia',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at
from wg_region_sources
where region_id = 'region-murcia'
on conflict do nothing;

insert into wg_region_music_pages (
    region_id,
    genre_id,
    role,
    source_id,
    source_type,
    source_url,
    source_title,
    evidence_text,
    confidence,
    raw_payload,
    created_at
)
select
    'region-region-of-murcia',
    genre_id,
    role,
    null,
    source_type,
    source_url,
    source_title,
    evidence_text,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-murcia',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at
from wg_region_music_pages
where region_id = 'region-murcia'
on conflict do nothing;

insert into wg_region_relationships (
    from_region_id,
    to_region_id,
    relation,
    source_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    review_reason,
    reviewer_model,
    raw_payload,
    created_at,
    updated_at
)
select
    case when from_region_id = 'region-murcia' then 'region-region-of-murcia' else from_region_id end,
    case when to_region_id = 'region-murcia' then 'region-region-of-murcia' else to_region_id end,
    relation,
    null,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    coalesce(review_reason, '') || ' Review resolution 0021: copied from merged region-murcia.',
    'gpt-5.4-mini',
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-murcia',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at,
    now()
from wg_region_relationships
where (from_region_id = 'region-murcia'
   or to_region_id = 'region-murcia')
  and (
      case when from_region_id = 'region-murcia' then 'region-region-of-murcia' else from_region_id end
  ) <> (
      case when to_region_id = 'region-murcia' then 'region-region-of-murcia' else to_region_id end
  )
on conflict do nothing;

insert into wg_region_genre_relationships (
    region_id,
    genre_id,
    relation,
    source_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    review_reason,
    reviewer_model,
    raw_payload,
    created_at,
    updated_at
)
select
    'region-region-of-murcia',
    genre_id,
    relation,
    null,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    coalesce(review_reason, '') || ' Review resolution 0021: copied from merged region-murcia.',
    'gpt-5.4-mini',
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-murcia',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at,
    now()
from wg_region_genre_relationships
where region_id = 'region-murcia'
on conflict do nothing;

update wg_region_merge_candidates
set status = 'merge',
    review_reason = 'Review resolution 0021: accepted duplicate region merge.',
    reviewer_model = 'gpt-5.4-mini',
    updated_at = now()
where left_region_id = 'region-murcia'
  and right_region_id = 'region-region-of-murcia';

delete from wg_regions
where id = 'region-murcia';

-- Merge Epirus (Greece) category evidence into the canonical Epirus node.
insert into wg_region_sources (
    region_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload,
    created_at
)
select
    'region-epirus',
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-epirus-greece',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at
from wg_region_sources
where region_id = 'region-epirus-greece'
on conflict do nothing;

insert into wg_region_music_pages (
    region_id,
    genre_id,
    role,
    source_id,
    source_type,
    source_url,
    source_title,
    evidence_text,
    confidence,
    raw_payload,
    created_at
)
select
    'region-epirus',
    genre_id,
    role,
    null,
    source_type,
    source_url,
    source_title,
    evidence_text,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-epirus-greece',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at
from wg_region_music_pages
where region_id = 'region-epirus-greece'
on conflict do nothing;

insert into wg_region_relationships (
    from_region_id,
    to_region_id,
    relation,
    source_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    review_reason,
    reviewer_model,
    raw_payload,
    created_at,
    updated_at
)
select
    case when from_region_id = 'region-epirus-greece' then 'region-epirus' else from_region_id end,
    case when to_region_id = 'region-epirus-greece' then 'region-epirus' else to_region_id end,
    relation,
    null,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    coalesce(review_reason, '') || ' Review resolution 0021: copied from merged region-epirus-greece.',
    'gpt-5.4-mini',
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-epirus-greece',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at,
    now()
from wg_region_relationships
where (from_region_id = 'region-epirus-greece'
   or to_region_id = 'region-epirus-greece')
  and (
      case when from_region_id = 'region-epirus-greece' then 'region-epirus' else from_region_id end
  ) <> (
      case when to_region_id = 'region-epirus-greece' then 'region-epirus' else to_region_id end
  )
on conflict do nothing;

insert into wg_region_genre_relationships (
    region_id,
    genre_id,
    relation,
    source_id,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    review_reason,
    reviewer_model,
    raw_payload,
    created_at,
    updated_at
)
select
    'region-epirus',
    genre_id,
    relation,
    null,
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    confidence,
    status,
    coalesce(review_reason, '') || ' Review resolution 0021: copied from merged region-epirus-greece.',
    'gpt-5.4-mini',
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-epirus-greece',
        'review_resolution', '0021_resolve_region_review_findings'
    ),
    created_at,
    now()
from wg_region_genre_relationships
where region_id = 'region-epirus-greece'
on conflict do nothing;

update wg_region_merge_candidates
set status = 'merge',
    review_reason = 'Review resolution 0021: accepted duplicate region merge.',
    reviewer_model = 'gpt-5.4-mini',
    updated_at = now()
where left_region_id = 'region-epirus'
  and right_region_id = 'region-epirus-greece';

delete from wg_regions
where id = 'region-epirus-greece';

-- Remove artifact/work pages from regional graph after findings are recorded.
delete from wg_regions
where id in (
    'region-hawaii-album',
    'region-tibet-album',
    'region-prince-of-qin-breaking-up-the-enemy-s-front'
);

commit;
