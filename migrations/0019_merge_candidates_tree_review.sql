-- 0019_merge_candidates_tree_review.sql
--
-- Staging tables for graph-wide merge candidate detection and GPT tree review.
-- These tables are review/audit substrate only; they do not merge genre rows
-- or change display edges.

begin;

create extension if not exists pg_trgm;

create table if not exists wg_genre_merge_candidates (
    candidate_key       text primary key,
    left_genre_id       text not null references wg_genres(id) on delete cascade,
    right_genre_id      text not null references wg_genres(id) on delete cascade,
    left_title          text not null,
    right_title         text not null,
    score               double precision not null default 0,
    title_similarity    double precision not null default 0,
    normalized_match    boolean not null default false,
    alias_overlap       integer not null default 0,
    redirect_match      boolean not null default false,
    shared_parent_count integer not null default 0,
    shared_child_count  integer not null default 0,
    evidence            jsonb not null default '{}'::jsonb,
    status              text not null default 'needs_review',
    review_reason       text,
    reviewer_model      text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint wg_genre_merge_candidates_pair_order check (left_genre_id < right_genre_id),
    constraint wg_genre_merge_candidates_score_valid check (score >= 0 and score <= 1),
    constraint wg_genre_merge_candidates_title_similarity_valid
        check (title_similarity >= 0 and title_similarity <= 1),
    constraint wg_genre_merge_candidates_status_valid check (status in (
        'needs_review',
        'merge',
        'do_not_merge',
        'already_redirect',
        'rejected'
    ))
);

create index if not exists wg_genre_merge_candidates_score_idx
    on wg_genre_merge_candidates(score desc, status);

create index if not exists wg_genre_merge_candidates_left_idx
    on wg_genre_merge_candidates(left_genre_id);

create index if not exists wg_genre_merge_candidates_right_idx
    on wg_genre_merge_candidates(right_genre_id);

create table if not exists wg_tree_review_batches (
    batch_key       text primary key,
    root_genre_id   text references wg_genres(id) on delete set null,
    root_title      text not null,
    node_count      integer not null default 0,
    edge_count      integer not null default 0,
    output_path     text,
    status          text not null default 'exported',
    reviewer_model  text,
    review_summary  text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    raw_payload     jsonb not null default '{}'::jsonb,
    constraint wg_tree_review_batches_status_valid check (status in (
        'exported',
        'reviewing',
        'reviewed',
        'imported'
    ))
);

create table if not exists wg_tree_review_findings (
    finding_key     text primary key,
    batch_key       text not null references wg_tree_review_batches(batch_key)
                    on delete cascade,
    finding_type    text not null,
    severity        text not null default 'medium',
    genre_id        text references wg_genres(id) on delete set null,
    related_genre_id text references wg_genres(id) on delete set null,
    title           text,
    related_title   text,
    recommendation  text not null,
    evidence        jsonb not null default '{}'::jsonb,
    reviewer_model  text,
    status          text not null default 'needs_review',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint wg_tree_review_findings_type_valid check (finding_type in (
        'merge_candidate',
        'wrong_parent',
        'missing_parent',
        'wrong_direction',
        'non_genre',
        'duplicate_region',
        'bad_relationship',
        'missing_relationship',
        'other'
    )),
    constraint wg_tree_review_findings_severity_valid check (severity in (
        'low',
        'medium',
        'high'
    )),
    constraint wg_tree_review_findings_status_valid check (status in (
        'needs_review',
        'accepted',
        'rejected'
    ))
);

create index if not exists wg_tree_review_findings_batch_idx
    on wg_tree_review_findings(batch_key, finding_type);

commit;
