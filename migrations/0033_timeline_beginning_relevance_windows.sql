-- 0033_timeline_beginning_relevance_windows.sql
--
-- Split timeline year estimates into two distinct concepts:
--   * beginning_*: uncertainty window for when the genre begins.
--   * relevance_*: observed direct-relevance window for future timeline spans.
--
-- year_start/year_end and estimated_start/estimated_end remain compatibility
-- fields for current layout behavior and mirror the beginning window.

begin;

alter table wg_timeline_year_hints
    add column if not exists beginning_start integer,
    add column if not exists beginning_end integer,
    add column if not exists beginning_mean double precision,
    add column if not exists beginning_sd double precision,
    add column if not exists beginning_observation_count integer,
    add column if not exists relevance_start integer,
    add column if not exists relevance_end integer,
    add column if not exists relevance_mean double precision,
    add column if not exists relevance_sd double precision,
    add column if not exists relevance_observation_count integer;

commit;
