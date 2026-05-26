-- 0027_timeline_year_hints.sql
--
-- Persist the best currently-known chronological hint per visible genre. This
-- keeps timeline-page opens from reparsing origin strings, summaries, and
-- categories on every request while still allowing the table to be rebuilt as
-- parser/scoring logic improves.

begin;

create table if not exists wg_timeline_year_hints (
    genre_id        text primary key references wg_genres(id) on delete cascade,
    has_hint        boolean not null,
    year_start      integer,
    year_end        integer,
    confidence      text,
    year_kind       text,
    source_type     text,
    source_field    text,
    evidence        text,
    reason          text,
    score           integer,
    parser_version  text not null,
    updated_at      timestamptz not null default now(),
    constraint wg_timeline_year_hints_confidence_valid check (
        confidence is null or confidence in ('low', 'medium', 'high')
    ),
    constraint wg_timeline_year_hints_consistent check (
        (
            has_hint = false
            and year_start is null
            and year_end is null
            and confidence is null
            and year_kind is null
            and source_type is null
            and source_field is null
            and evidence is null
            and reason is null
            and score is null
        )
        or (
            has_hint = true
            and year_start is not null
            and confidence is not null
            and year_kind is not null
            and source_type is not null
            and source_field is not null
            and evidence is not null
            and reason is not null
            and score is not null
        )
    )
);

create index if not exists wg_timeline_year_hints_year_idx
    on wg_timeline_year_hints(year_start)
    where has_hint = true;

create index if not exists wg_timeline_year_hints_confidence_idx
    on wg_timeline_year_hints(confidence)
    where has_hint = true;

commit;
