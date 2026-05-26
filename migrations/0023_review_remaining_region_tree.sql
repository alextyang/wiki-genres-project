-- 0023_review_remaining_region_tree.sql
--
-- Resolve remaining unreviewed region nodes. This pass de-containerizes
-- adjective/category-derived region nodes, connects isolated places to their
-- list/category parents, and fixes country/territory kinds found outside the
-- first GPT review batches.

begin;

create temporary table tmp_region_merge_map (
    source_region_id text primary key,
    target_region_id text not null
) on commit drop;

insert into tmp_region_merge_map (source_region_id, target_region_id)
values
    ('region-algerian', 'region-algeria'),
    ('region-argentine', 'region-argentina'),
    ('region-azerbaijani', 'region-azerbaijan'),
    ('region-belgian', 'region-belgium'),
    ('region-brazilian', 'region-brazil'),
    ('region-bulgarian', 'region-bulgaria'),
    ('region-canadian', 'region-canada'),
    ('region-colombian', 'region-colombia'),
    ('region-croatian', 'region-croatia'),
    ('region-cuban', 'region-cuba'),
    ('region-dominican', 'region-dominican-republic'),
    ('region-english', 'region-england'),
    ('region-greek', 'region-greece'),
    ('region-haitian', 'region-haiti'),
    ('region-hungarian', 'region-hungary'),
    ('region-icelandic', 'region-iceland'),
    ('region-indian', 'region-india'),
    ('region-iranian', 'region-iran'),
    ('region-irish', 'region-ireland'),
    ('region-jamaican', 'region-jamaica'),
    ('region-kazakhstani', 'region-kazakhstan'),
    ('region-kenyan', 'region-kenya'),
    ('region-korean', 'region-korea'),
    ('region-kyrgyzstani', 'region-kyrgyzstan'),
    ('region-liberian', 'region-liberia'),
    ('region-lithuanian', 'region-lithuania'),
    ('region-malaysian', 'region-malaysia'),
    ('region-maltese', 'region-malta'),
    ('region-mexican', 'region-mexico'),
    ('region-moroccan', 'region-morocco'),
    ('region-nepalese', 'region-nepal'),
    ('region-nigerian', 'region-nigeria'),
    ('region-norwegian', 'region-norway'),
    ('region-pakistani', 'region-pakistan'),
    ('region-panamanian', 'region-panama'),
    ('region-paraguayan', 'region-paraguay'),
    ('region-peruvian', 'region-peru'),
    ('region-philippine', 'region-philippines'),
    ('region-polish', 'region-poland'),
    ('region-portuguese', 'region-portugal'),
    ('region-puerto-rican', 'region-puerto-rico'),
    ('region-punjabi', 'region-punjab'),
    ('region-romanian', 'region-romania'),
    ('region-russian', 'region-russia'),
    ('region-scottish', 'region-scotland'),
    ('region-serbian', 'region-serbia'),
    ('region-sierra-leonean', 'region-sierra-leone'),
    ('region-slovak', 'region-slovakia'),
    ('region-south-african', 'region-south-africa'),
    ('region-south-korean', 'region-south-korea'),
    ('region-spanish', 'region-spain'),
    ('region-swedish', 'region-sweden'),
    ('region-tanzanian', 'region-tanzania'),
    ('region-thai', 'region-thailand'),
    ('region-turkish', 'region-turkey'),
    ('region-ukrainian', 'region-ukraine'),
    ('region-uruguayan', 'region-uruguay'),
    ('region-uzbekistani', 'region-uzbekistan'),
    ('region-venezuelan', 'region-venezuela'),
    ('region-welsh', 'region-wales');

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
        'review_resolution', '0023_review_remaining_region_tree'
    ),
    s.created_at
from wg_region_sources s
join tmp_region_merge_map m on m.source_region_id = s.region_id
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
    m.target_region_id,
    e.genre_id,
    e.relation,
    null,
    e.source_type,
    e.source_url,
    e.source_title,
    e.source_section,
    e.evidence_text,
    e.confidence,
    e.status,
    coalesce(e.review_reason, '') || ' Review resolution 0023: copied from adjective/category container region.',
    'manual',
    e.raw_payload || jsonb_build_object(
        'merged_from_region_id', m.source_region_id,
        'review_resolution', '0023_review_remaining_region_tree'
    ),
    e.created_at,
    now()
from wg_region_genre_relationships e
join tmp_region_merge_map m on m.source_region_id = e.region_id
where e.status = 'accepted'
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
    e.from_region_id,
    m.target_region_id,
    e.relation,
    null,
    e.source_type,
    e.source_url,
    e.source_title,
    e.source_section,
    e.evidence_text,
    e.confidence,
    e.status,
    coalesce(e.review_reason, '') || ' Review resolution 0023: rewired from adjective/category container parent.',
    'manual',
    e.raw_payload || jsonb_build_object(
        'merged_from_region_id', m.source_region_id,
        'review_resolution', '0023_review_remaining_region_tree'
    ),
    e.created_at,
    now()
from wg_region_relationships e
join tmp_region_merge_map m on m.source_region_id = e.to_region_id
where e.status = 'accepted'
  and e.from_region_id <> m.target_region_id
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
    m.target_region_id,
    e.to_region_id,
    e.relation,
    null,
    e.source_type,
    e.source_url,
    e.source_title,
    e.source_section,
    e.evidence_text,
    e.confidence,
    e.status,
    coalesce(e.review_reason, '') || ' Review resolution 0023: rewired from adjective/category container child.',
    'manual',
    e.raw_payload || jsonb_build_object(
        'merged_from_region_id', m.source_region_id,
        'review_resolution', '0023_review_remaining_region_tree'
    ),
    e.created_at,
    now()
from wg_region_relationships e
join tmp_region_merge_map m on m.source_region_id = e.from_region_id
where e.status = 'accepted'
  and m.target_region_id <> e.to_region_id
on conflict do nothing;

delete from wg_regions
where id in (select source_region_id from tmp_region_merge_map);

-- Remove list headings and genre names that were incorrectly materialized as
-- regions. Their meaningful edges already exist on real region nodes or were
-- intentionally broad list buckets.
delete from wg_regions
where id in (
    'region-benna',
    'region-bibliography',
    'region-calypso',
    'region-cariso',
    'region-chante-mas',
    'region-chutney',
    'region-lists-of',
    'region-mizik-rasin',
    'region-soca',
    'region-sources',
    'region-subgenres-of-latin-music',
    'region-twoubadou'
);

create temporary table tmp_region_parent_map (
    child_region_id text not null,
    parent_region_id text not null,
    relation text not null,
    child_kind text,
    primary key (child_region_id, parent_region_id, relation)
) on commit drop;

insert into tmp_region_parent_map (child_region_id, parent_region_id, relation, child_kind)
values
    ('region-kabylie', 'region-algeria', 'part_of', 'subregion'),
    ('region-american-and-canadian-wests', 'region-canada', 'cultural_region_of', 'cultural_region'),
    ('region-american-and-canadian-wests', 'region-united-states', 'cultural_region_of', 'cultural_region'),
    ('region-canada-s-maritimes', 'region-canada', 'part_of', 'subregion'),
    ('region-hebei', 'region-china', 'part_of', 'subregion'),
    ('region-hong-kong', 'region-china', 'admin_parent', 'territory'),
    ('region-manchuria', 'region-china', 'historical_region_of', 'historical_region'),
    ('region-karelia', 'region-finland', 'cultural_region_of', 'cultural_region'),
    ('region-karelia', 'region-russia', 'cultural_region_of', 'cultural_region'),
    ('region-aland', 'region-finland', 'admin_parent', 'territory'),
    ('region-martinique-and-guadeloupe', 'region-france', 'admin_parent', 'territory'),
    ('region-martinique-and-guadeloupe', 'region-caribbean', 'cultural_region_of', 'territory'),
    ('region-wallis-and-futuna', 'region-france', 'admin_parent', 'territory'),
    ('region-aegean-islands', 'region-greece', 'part_of', 'subregion'),
    ('region-cyclades', 'region-greece', 'part_of', 'subregion'),
    ('region-dodecanese-islands', 'region-greece', 'part_of', 'subregion'),
    ('region-lesbos', 'region-greece', 'part_of', 'subregion'),
    ('region-peloponnesos', 'region-greece', 'part_of', 'subregion'),
    ('region-mesopotamia', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-ancient-india', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-ancient-persia', 'region-historical-genres', 'historical_region_of', 'historical_region'),
    ('region-jammu', 'region-india', 'part_of', 'subregion'),
    ('region-kashmir', 'region-india', 'part_of', 'subregion'),
    ('region-kerala', 'region-india', 'part_of', 'subregion'),
    ('region-orissa', 'region-india', 'part_of', 'subregion'),
    ('region-uttaranchal', 'region-india', 'part_of', 'subregion'),
    ('region-friuli', 'region-italy', 'part_of', 'subregion'),
    ('region-latium', 'region-italy', 'part_of', 'subregion'),
    ('region-lucca', 'region-italy', 'part_of', 'city'),
    ('region-puglia', 'region-italy', 'part_of', 'subregion'),
    ('region-okinawa', 'region-japan', 'part_of', 'subregion'),
    ('region-aruba-and-the-netherlands-antilles', 'region-netherlands', 'admin_parent', 'territory'),
    ('region-aruba-and-the-netherlands-antilles', 'region-caribbean', 'cultural_region_of', 'territory'),
    ('region-altai', 'region-russia', 'part_of', 'subregion'),
    ('region-astrakhan', 'region-russia', 'part_of', 'subregion'),
    ('region-buryatia', 'region-russia', 'part_of', 'subregion'),
    ('region-dagestan', 'region-russia', 'part_of', 'subregion'),
    ('region-irkutsk', 'region-russia', 'part_of', 'subregion'),
    ('region-kaliningrad', 'region-russia', 'part_of', 'subregion'),
    ('region-nenetsia', 'region-russia', 'part_of', 'subregion'),
    ('region-rostov-on-don', 'region-russia', 'part_of', 'city'),
    ('region-sakha', 'region-russia', 'part_of', 'subregion'),
    ('region-tuva', 'region-russia', 'part_of', 'subregion'),
    ('region-udmurtia', 'region-russia', 'part_of', 'subregion'),
    ('region-basque-country', 'region-spain', 'part_of', 'subregion'),
    ('region-castile-madrid-and-leon', 'region-spain', 'part_of', 'subregion'),
    ('region-galicia-cantabria-and-asturias', 'region-spain', 'part_of', 'subregion'),
    ('region-navarre-and-la-rioja', 'region-spain', 'part_of', 'subregion'),
    ('region-valencia', 'region-spain', 'part_of', 'subregion'),
    ('region-karadeniz', 'region-turkey', 'part_of', 'subregion'),
    ('region-falkland-islands', 'region-united-kingdom', 'admin_parent', 'territory'),
    ('region-saint-helena', 'region-united-kingdom', 'admin_parent', 'territory'),
    ('region-austin', 'region-united-states', 'part_of', 'city'),
    ('region-charlotte', 'region-united-states', 'part_of', 'city'),
    ('region-fort-worth', 'region-united-states', 'part_of', 'city'),
    ('region-milwaukee', 'region-united-states', 'part_of', 'city'),
    ('region-olympia', 'region-united-states', 'part_of', 'city'),
    ('region-san-diego', 'region-united-states', 'part_of', 'city'),
    ('region-san-francisco', 'region-united-states', 'part_of', 'city'),
    ('region-tunis', 'region-tunisia', 'part_of', 'city'),
    ('region-vatican-city', 'region-europe', 'admin_parent', 'country'),
    ('region-middle-east', 'region-asia', 'cultural_region_of', 'cultural_region'),
    ('region-nordic', 'region-europe', 'cultural_region_of', 'cultural_region'),
    ('region-northern-europe', 'region-europe', 'part_of', 'subregion'),
    ('region-southeastern-europe', 'region-europe', 'part_of', 'subregion'),
    ('region-north-america', 'region-americas', 'part_of', 'cultural_region'),
    ('region-south-america', 'region-americas', 'part_of', 'cultural_region'),
    ('region-yucatan-mexico', 'region-mexico', 'part_of', 'subregion'),
    ('region-yucatan-mexico', 'region-caribbean', 'cultural_region_of', 'subregion'),
    ('region-dutch-west-indies', 'region-caribbean', 'historical_region_of', 'historical_region'),
    ('region-dutch-west-indies', 'region-netherlands', 'historical_region_of', 'historical_region');

update wg_regions r
set kind = m.child_kind,
    raw_payload = r.raw_payload || jsonb_build_object(
        'review_resolution', '0023_review_remaining_region_tree',
        'previous_kind', r.kind
    ),
    updated_at = now()
from tmp_region_parent_map m
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
    'Remaining region graph review',
    'Manual remaining-region review connected the node to its supported broader region.',
    0.82,
    'accepted',
    'Review resolution 0023: connected remaining unreviewed regional node.',
    'manual',
    jsonb_build_object('review_resolution', '0023_review_remaining_region_tree'),
    now(),
    now()
from tmp_region_parent_map m
where m.child_region_id <> m.parent_region_id
on conflict do nothing;

-- Country and country-like rows still misclassified after prior review.
update wg_regions
set kind = 'country',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0023_review_remaining_region_tree',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-algeria',
    'region-argentina',
    'region-azerbaijan',
    'region-belgium',
    'region-brazil',
    'region-bulgaria',
    'region-croatia',
    'region-finland',
    'region-hungary',
    'region-iceland',
    'region-japan',
    'region-kazakhstan',
    'region-kenya',
    'region-kyrgyzstan',
    'region-liberia',
    'region-lithuania',
    'region-malaysia',
    'region-malta',
    'region-mexico',
    'region-morocco',
    'region-nigeria',
    'region-norway',
    'region-poland',
    'region-portugal',
    'region-romania',
    'region-russia',
    'region-sierra-leone',
    'region-slovakia',
    'region-south-africa',
    'region-south-korea',
    'region-sweden',
    'region-tanzania',
    'region-thailand',
    'region-tunisia',
    'region-turkey',
    'region-ukraine',
    'region-uzbekistan'
)
  and kind <> 'country';

update wg_regions
set kind = 'territory',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0023_review_remaining_region_tree',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-falkland-islands',
    'region-hong-kong',
    'region-saint-helena',
    'region-wallis-and-futuna',
    'region-aland'
)
  and kind <> 'territory';

update wg_regions
set kind = 'historical_region',
    raw_payload = raw_payload || jsonb_build_object(
        'review_resolution', '0023_review_remaining_region_tree',
        'previous_kind', kind
    ),
    updated_at = now()
where id in (
    'region-ancient-music',
    'region-colonial-mexico',
    'region-elizabethan-era',
    'region-franco-flemish',
    'region-medieval',
    'region-medieval-islamic-world'
)
  and kind <> 'historical_region';

commit;
