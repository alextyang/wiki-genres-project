-- 0031_accept_youtube_music_playlist_urls.sql
--
-- YouTube Music links are public YouTube links and are useful as curated
-- playlist/video sources. Keep the table restricted to YouTube-owned hosts.

begin;

alter table if exists wg_genre_youtube_playlist_tracks
    drop constraint if exists wg_genre_youtube_playlist_tracks_youtube_url_valid;

alter table if exists wg_genre_youtube_playlist_tracks
    add constraint wg_genre_youtube_playlist_tracks_youtube_url_valid
        check (
            youtube_url ~* '^(https?://((www|music)\.)?youtube\.com/|https?://youtu\.be/)'
        );

commit;
