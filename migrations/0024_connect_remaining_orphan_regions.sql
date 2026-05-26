-- 0024_connect_remaining_orphan_regions.sql
--
-- Finish the remaining orphan review: merge empty demonym containers into real
-- country nodes, connect valid cultural/historical regions, and remove broad
-- list buckets that should not remain as displayable region nodes.

begin;

create temporary table tmp_empty_demonym_map (
    source_region_id text primary key,
    target_region_id text not null
) on commit drop;

insert into tmp_empty_demonym_map (source_region_id, target_region_id)
values
    ('region-albanian', 'region-albania'),
    ('region-armenian', 'region-armenia'),
    ('region-austrian', 'region-austria'),
    ('region-bangladeshi', 'region-bangladesh'),
    ('region-bhutanese', 'region-bhutan'),
    ('region-costa-rican', 'region-costa-rica'),
    ('region-czech', 'region-czech-republic'),
    ('region-estonian', 'region-estonia'),
    ('region-finnish', 'region-finland'),
    ('region-ghanaian', 'region-ghana'),
    ('region-macedonian', 'region-north-macedonia'),
    ('region-mauritian', 'region-mauritius'),
    ('region-moldovan', 'region-moldova'),
    ('region-north-korean', 'region-north-korea'),
    ('region-slovenian', 'region-slovenia'),
    ('region-swiss', 'region-switzerland'),
    ('region-vietnamese', 'region-vietnam');

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
    m.target_region_id,
    s.source_type,
    s.source_url,
    s.source_title,
    s.source_section,
    s.evidence_text,
    s.extractor_model,
    s.confidence,
    s.raw_payload || jsonb_build_object(
        'merged_from_region_id', m.source_region_id,
        'review_resolution', '0024_connect_remaining_orphan_regions'
    ),
    s.created_at
from wg_region_sources s
join tmp_empty_demonym_map m on m.source_region_id = s.region_id
on conflict do nothing;

delete from wg_regions
where id in (select source_region_id from tmp_empty_demonym_map);

-- Duplicate or superseded country names.
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
    'region-ivory-coast',
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-cote-d-ivoire',
        'review_resolution', '0024_connect_remaining_orphan_regions'
    ),
    created_at
from wg_region_sources
where region_id = 'region-cote-d-ivoire'
on conflict do nothing;

delete from wg_regions where id = 'region-cote-d-ivoire';

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
    'region-eswatini',
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-swaziland',
        'review_resolution', '0024_connect_remaining_orphan_regions'
    ),
    created_at
from wg_region_sources
where region_id = 'region-swaziland'
on conflict do nothing;

delete from wg_regions where id = 'region-swaziland';

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
    'region-north-macedonia',
    source_type,
    source_url,
    source_title,
    source_section,
    evidence_text,
    extractor_model,
    confidence,
    raw_payload || jsonb_build_object(
        'merged_from_region_id', 'region-republic-of-macedonia',
        'review_resolution', '0024_connect_remaining_orphan_regions'
    ),
    created_at
from wg_region_sources
where region_id = 'region-republic-of-macedonia'
on conflict do nothing;

delete from wg_regions where id = 'region-republic-of-macedonia';

-- Broad list artifacts that are not region nodes.
delete from wg_regions
where id in (
    'region-latin'
);

create temporary table tmp_orphan_parent_map (
    child_region_id text not null,
    parent_region_id text not null,
    relation text not null,
    child_kind text,
    primary key (child_region_id, parent_region_id, relation)
) on commit drop;

insert into tmp_orphan_parent_map (child_region_id, parent_region_id, relation, child_kind)
values
    ('region-ancient-music', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-colonial-mexico', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-elizabethan-era', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-franco-flemish', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-medieval', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-medieval-islamic-world', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-al-andalus', 'region-spain', 'historical_region_of', 'historical_region'),
    ('region-al-andalus', 'region-middle-east', 'cultural_region_of', 'historical_region'),
    ('region-ainu', 'region-japan', 'cultural_region_of', 'cultural_region'),
    ('region-assyria', 'region-middle-east', 'historical_region_of', 'historical_region'),
    ('region-berber-cultural-region', 'region-north-africa', 'cultural_region_of', 'cultural_region'),
    ('region-buryat', 'region-russia', 'cultural_region_of', 'cultural_region'),
    ('region-chechnya', 'region-russia', 'part_of', 'subregion'),
    ('region-coptic', 'region-egypt', 'cultural_region_of', 'cultural_region'),
    ('region-crimean-tatar', 'region-ukraine', 'cultural_region_of', 'cultural_region'),
    ('region-himalayas', 'region-south-asia', 'part_of', 'subregion'),
    ('region-indigenous-australia', 'region-australia', 'cultural_region_of', 'cultural_region'),
    ('region-low-countries', 'region-netherlands', 'cultural_region_of', 'cultural_region'),
    ('region-low-countries', 'region-belgium', 'cultural_region_of', 'cultural_region'),
    ('region-mari', 'region-russia', 'cultural_region_of', 'cultural_region'),
    ('region-meitei', 'region-india', 'cultural_region_of', 'cultural_region'),
    ('region-immigrant-communities-in-the-united-states', 'region-united-states', 'diaspora_region_of', 'diaspora_region');

update wg_regions r
set kind = m.child_kind,
    raw_payload = r.raw_payload || jsonb_build_object(
        'review_resolution', '0024_connect_remaining_orphan_regions',
        'previous_kind', r.kind
    ),
    updated_at = now()
from tmp_orphan_parent_map m
where r.id = m.child_region_id
  and m.child_kind is not null
  and r.kind <> m.child_kind;

insert into wg_region_relationships (
    from_region_id,
    to_region_id,
    relation,
    source_type,
    source_title,
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
    m.child_region_id,
    m.parent_region_id,
    m.relation,
    'manual',
    'Remaining orphan region review',
    'Manual remaining-region review connected a valid orphan node to its broader context.',
    0.8,
    'accepted',
    'Review resolution 0024: connected remaining orphan regional node.',
    'manual',
    jsonb_build_object('review_resolution', '0024_connect_remaining_orphan_regions'),
    now(),
    now()
from tmp_orphan_parent_map m
where m.child_region_id <> m.parent_region_id
on conflict do nothing;

update wg_regions
set kind = 'historical_region',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0024_connect_remaining_orphan_regions',
        'previous_kind', kind
    ),
    updated_at = now()
where id = 'region-historical-genres'
  and kind <> 'historical_region';

update wg_regions
set kind = 'continent',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0024_connect_remaining_orphan_regions',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-africa',
    'region-asia',
    'region-europe',
    'region-oceania'
)
  and kind <> 'continent';

update wg_regions
set kind = 'country',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0024_connect_remaining_orphan_regions',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-albania',
    'region-armenia',
    'region-austria',
    'region-bhutan',
    'region-costa-rica',
    'region-czech-republic',
    'region-egypt',
    'region-eswatini',
    'region-estonia',
    'region-ghana',
    'region-ivory-coast',
    'region-mauritius',
    'region-moldova',
    'region-north-korea',
    'region-north-macedonia',
    'region-slovenia',
    'region-vietnam'
)
  and kind <> 'country';

commit;
