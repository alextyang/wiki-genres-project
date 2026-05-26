-- 0039_playlist_discovery_version.sql
--
-- Distinguish playlist track import/discovery batches so enrichment and
-- preflight passes can target one batch without touching another.

begin;

alter table if exists wg_genre_youtube_playlist_tracks
    add column if not exists discovery_version text not null default 'manual';

create index if not exists wg_genre_youtube_playlist_tracks_discovery_version
    on wg_genre_youtube_playlist_tracks(discovery_version, genre_id);

commit;
