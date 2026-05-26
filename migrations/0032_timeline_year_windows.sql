-- 0032_timeline_year_windows.sql
--
-- Store richer timeline estimates in addition to the start year currently used
-- by the timeline layout. The window fields come from weighted temporal
-- observations so the UI can later show uncertainty without reparsing text.

begin;

alter table wg_timeline_year_hints
    add column if not exists estimated_start integer,
    add column if not exists estimated_end integer,
    add column if not exists year_mean double precision,
    add column if not exists year_sd double precision,
    add column if not exists year_observation_count integer,
    add column if not exists excluded_reason text;

commit;
