-- 0030_region_production_review.sql
--
-- Staging substrate for the second regional production review pass. GPT review
-- decisions land here first, then deterministic high-confidence decisions can
-- be applied back to the regional staging graph.

begin;

create table if not exists wg_region_production_review_batches (
    batch_key       text primary key,
    review_type     text not null,
    output_path     text,
    rows_exported   integer not null default 0,
    status          text not null default 'exported',
    reviewer_model  text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    raw_payload     jsonb not null default '{}'::jsonb,
    constraint wg_region_production_review_batches_type_valid check (review_type in (
        'zero_child_source_review',
        'parentless_region_review',
        'broad_region_genre_review',
        'invalid_region_title_review'
    )),
    constraint wg_region_production_review_batches_status_valid check (status in (
        'exported',
        'reviewed',
        'imported',
        'applied'
    ))
);

create table if not exists wg_region_production_review_decisions (
    decision_key      text primary key,
    batch_key         text references wg_region_production_review_batches(batch_key)
                      on delete set null,
    review_type       text not null,
    subject_key       text not null,
    region_id         text references wg_regions(id) on delete cascade,
    region_genre_relationship_id bigint references wg_region_genre_relationships(id)
                      on delete cascade,
    genre_id          text references wg_genres(id) on delete set null,
    decision          text not null,
    confidence        text not null,
    explanation       text not null,
    target_parents    jsonb not null default '[]'::jsonb,
    candidate_genres  jsonb not null default '[]'::jsonb,
    title_replacement text,
    status            text not null default 'imported',
    reviewer_model    text,
    applied_at        timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    raw_payload        jsonb not null default '{}'::jsonb,
    constraint wg_region_production_review_decisions_type_valid check (review_type in (
        'zero_child_source_review',
        'parentless_region_review',
        'broad_region_genre_review',
        'invalid_region_title_review'
    )),
    constraint wg_region_production_review_decisions_decision_valid check (decision in (
        'keep',
        'collapse',
        'anchor',
        'extract_candidates',
        'reject',
        'rename',
        'needs_human',
        'keep_broad',
        'move_to_specific_regions',
        'inherit_from_children',
        'context_only'
    )),
    constraint wg_region_production_review_decisions_confidence_valid check (confidence in (
        'high',
        'medium',
        'low'
    )),
    constraint wg_region_production_review_decisions_status_valid check (status in (
        'imported',
        'needs_human',
        'applied',
        'rejected'
    ))
);

create index if not exists wg_region_production_review_decisions_type_idx
    on wg_region_production_review_decisions(review_type, decision, confidence, status);

create index if not exists wg_region_production_review_decisions_region_idx
    on wg_region_production_review_decisions(region_id);

create index if not exists wg_region_production_review_decisions_rgr_idx
    on wg_region_production_review_decisions(region_genre_relationship_id);

commit;
