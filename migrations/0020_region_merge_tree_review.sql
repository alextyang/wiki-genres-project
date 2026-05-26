-- 0020_region_merge_tree_review.sql
--
-- Region-graph-specific duplicate detection and GPT review staging. These
-- tables are separate from genre tree review so regional hierarchy, parallel
-- parents, and region-to-genre attachments can be audited independently.

begin;

create extension if not exists pg_trgm;

create table if not exists wg_region_merge_candidates (
    candidate_key       text primary key,
    left_region_id      text not null references wg_regions(id) on delete cascade,
    right_region_id     text not null references wg_regions(id) on delete cascade,
    left_name           text not null,
    right_name          text not null,
    score               double precision not null default 0,
    name_similarity     double precision not null default 0,
    normalized_match    boolean not null default false,
    same_kind           boolean not null default false,
    source_overlap_count integer not null default 0,
    shared_parent_count integer not null default 0,
    shared_child_count  integer not null default 0,
    shared_genre_count  integer not null default 0,
    evidence            jsonb not null default '{}'::jsonb,
    status              text not null default 'needs_review',
    review_reason       text,
    reviewer_model      text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_region_merge_candidates_pair_order check (left_region_id < right_region_id),
    constraint wg_region_merge_candidates_score_valid check (score >= 0 and score <= 1),
    constraint wg_region_merge_candidates_name_similarity_valid
        check (name_similarity >= 0 and name_similarity <= 1),
    constraint wg_region_merge_candidates_status_valid check (status in (
        'needs_review',
        'merge',
        'do_not_merge',
        'rejected'
    ))
);

create index if not exists wg_region_merge_candidates_score_idx
    on wg_region_merge_candidates(score desc, status);

create index if not exists wg_region_merge_candidates_left_idx
    on wg_region_merge_candidates(left_region_id);

create index if not exists wg_region_merge_candidates_right_idx
    on wg_region_merge_candidates(right_region_id);

create table if not exists wg_region_tree_review_batches (
    batch_key       text primary key,
    root_region_id  text references wg_regions(id) on delete set null,
    root_name       text not null,
    region_count    integer not null default 0,
    region_edge_count integer not null default 0,
    genre_edge_count integer not null default 0,
    output_path     text,
    status          text not null default 'exported',
    reviewer_model  text,
    review_summary  text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    raw_payload     jsonb not null default '{}'::jsonb,
    constraint wg_region_tree_review_batches_status_valid check (status in (
        'exported',
        'reviewing',
        'reviewed',
        'imported'
    ))
);

create table if not exists wg_region_tree_review_findings (
    finding_key      text primary key,
    batch_key        text not null references wg_region_tree_review_batches(batch_key)
                     on delete cascade,
    finding_type     text not null,
    severity         text not null default 'medium',
    region_id        text references wg_regions(id) on delete set null,
    related_region_id text references wg_regions(id) on delete set null,
    genre_id         text references wg_genres(id) on delete set null,
    title            text,
    related_title    text,
    recommendation   text not null,
    evidence         jsonb not null default '{}'::jsonb,
    reviewer_model   text,
    status           text not null default 'needs_review',
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint wg_region_tree_review_findings_type_valid check (finding_type in (
        'duplicate_region',
        'wrong_region_parent',
        'missing_region_parent',
        'wrong_region_direction',
        'wrong_region_genre',
        'missing_region_genre',
        'missing_region',
        'bad_region_node',
        'bad_relationship',
        'kind_mismatch',
        'other'
    )),
    constraint wg_region_tree_review_findings_severity_valid check (severity in (
        'low',
        'medium',
        'high'
    )),
    constraint wg_region_tree_review_findings_status_valid check (status in (
        'needs_review',
        'accepted',
        'rejected'
    ))
);

create index if not exists wg_region_tree_review_findings_batch_idx
    on wg_region_tree_review_findings(batch_key, finding_type);

commit;
