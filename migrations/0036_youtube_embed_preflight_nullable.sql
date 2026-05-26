-- 0036_youtube_embed_preflight_nullable.sql
--
-- Allow recording transient/unknown preflight results without forcing a
-- true/false decision.

begin;

alter table if exists wg_youtube_embed_preflight_cache
    alter column is_embeddable drop not null;

commit;

