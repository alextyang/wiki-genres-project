-- 0034_allow_blank_playlist_artists.sql
--
-- Playlist exports may not always have reliable artist attribution. Keep the
-- title and URL required, but allow an empty artist field.

begin;

alter table if exists wg_genre_youtube_playlist_tracks
    drop constraint if exists wg_genre_youtube_playlist_tracks_artist_nonempty;

commit;
