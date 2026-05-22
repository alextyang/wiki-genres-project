-- 0001_initial.sql — schema for the wiki-genres mirror.
--
-- Conventions:
--   - All tables prefixed `wg_`.
--   - Timestamps in UTC (`timestamptz`).
--   - Genre identity rooted in `wg_genres.id`, a stable slug derived from the
--     Wikidata QID where available; falls back to a hash of the canonical title.
--   - Edges store `to_raw_label` verbatim so unresolved targets can be re-linked
--     later without re-fetching upstream.
--
-- See docs/PLAN.md § 4 for the rationale behind each table.

begin;

-- =========================================================================
-- Core graph
-- =========================================================================

create table wg_genres (
    id                  text primary key,
    wikidata_qid        text unique,
    wikipedia_title     text not null unique,
    wikipedia_url       text not null,
    summary             text,
    infobox_color       text,
    is_seed             boolean not null default false,
    has_infobox         boolean not null default false,
    raw_wikitext_sha256 text,
    upstream_revision   bigint,
    first_seen_at       timestamptz not null default now(),
    last_fetched_at     timestamptz not null default now(),
    last_changed_at     timestamptz not null default now(),
    deleted_at          timestamptz,
    constraint wg_genres_color_hex check (
        infobox_color is null or infobox_color ~ '^#[0-9A-Fa-f]{6}$'
    )
);

create index wg_genres_last_changed_at_idx on wg_genres(last_changed_at);
create index wg_genres_deleted_at_idx on wg_genres(deleted_at) where deleted_at is not null;

create table wg_redirects (
    from_title          text primary key,
    to_genre_id         text not null references wg_genres(id) on delete cascade,
    first_seen_at       timestamptz not null default now()
);

create index wg_redirects_to_genre_id_idx on wg_redirects(to_genre_id);

create table wg_aliases (
    genre_id            text not null references wg_genres(id) on delete cascade,
    alias               text not null,
    source              text not null,
    first_seen_at       timestamptz not null default now(),
    primary key (genre_id, alias, source),
    constraint wg_aliases_source_valid check (source in (
        'other_names', 'wikidata_alias', 'redirect'
    ))
);

create index wg_aliases_alias_lower_idx on wg_aliases(lower(alias));

create table wg_edges (
    from_genre_id       text not null references wg_genres(id) on delete cascade,
    to_genre_id         text references wg_genres(id) on delete cascade,
    to_raw_label        text not null,
    relation            text not null,
    source              text not null,
    ordinal             integer not null default 0,
    first_seen_at       timestamptz not null default now(),
    primary key (from_genre_id, relation, source, ordinal),
    constraint wg_edges_relation_valid check (relation in (
        'subgenre', 'derivative', 'stylistic_origin', 'cultural_origin',
        'fusion_genre', 'regional_scene', 'local_scene', 'other_name',
        'influenced_by', 'subclass_of', 'part_of', 'instance_of'
    )),
    constraint wg_edges_source_valid check (source in ('infobox', 'wikidata'))
);

create index wg_edges_to_genre_id_idx on wg_edges(to_genre_id) where to_genre_id is not null;
create index wg_edges_relation_idx on wg_edges(relation);
create index wg_edges_unresolved_idx on wg_edges(from_genre_id) where to_genre_id is null;

create table wg_origins (
    genre_id            text not null references wg_genres(id) on delete cascade,
    kind                text not null,
    value               text not null,
    parsed_year_start   integer,
    parsed_year_end     integer,
    parsed_region       text,
    primary key (genre_id, kind, value),
    constraint wg_origins_kind_valid check (kind in ('cultural', 'temporal'))
);

create table wg_instruments (
    genre_id            text not null references wg_genres(id) on delete cascade,
    instrument          text not null,
    instrument_genre_id text references wg_genres(id) on delete set null,
    primary key (genre_id, instrument)
);

create table wg_categories (
    genre_id            text not null references wg_genres(id) on delete cascade,
    category            text not null,
    primary key (genre_id, category)
);

-- =========================================================================
-- Sync & provenance
-- =========================================================================

create table wg_fetch_log (
    id                  bigserial primary key,
    url                 text not null,
    fetched_at          timestamptz not null default now(),
    http_status         integer not null,
    content_sha256      text,
    elapsed_ms          integer,
    via                 text not null,
    constraint wg_fetch_log_via_valid check (via in (
        'bootstrap', 'sync_worker', 'scheduler', 'manual'
    ))
);

create index wg_fetch_log_url_idx on wg_fetch_log(url, fetched_at desc);
create index wg_fetch_log_fetched_at_idx on wg_fetch_log(fetched_at);

create table wg_revisions (
    genre_id            text not null references wg_genres(id) on delete cascade,
    upstream_revision   bigint not null,
    fetched_at          timestamptz not null default now(),
    content_sha256      text not null,
    triggered_by        text not null,
    diff_summary        jsonb,
    primary key (genre_id, upstream_revision),
    constraint wg_revisions_triggered_by_valid check (triggered_by in (
        'bootstrap', 'eventstream', 'sparql', 'reconciler', 'manual'
    ))
);

create index wg_revisions_fetched_at_idx on wg_revisions(fetched_at);

create table wg_frontier (
    title               text primary key,
    enqueued_at         timestamptz not null default now(),
    not_before          timestamptz not null default now(),
    reason              text not null,
    attempts            integer not null default 0,
    constraint wg_frontier_reason_valid check (reason in (
        'seed', 'eventstream', 'wikilink', 'sparql', 'reconciler', 'manual'
    ))
);

create index wg_frontier_not_before_idx on wg_frontier(not_before);

create table wg_sync_state (
    key                 text primary key,
    value               jsonb not null,
    updated_at          timestamptz not null default now()
);

create table wg_snapshots (
    id                  text primary key,
    kind                text not null,
    started_at          timestamptz not null default now(),
    finished_at         timestamptz,
    nodes_total         integer,
    edges_total         integer,
    notes               text,
    constraint wg_snapshots_kind_valid check (kind in ('bootstrap', 'dump_audit', 'reconciler'))
);

commit;
