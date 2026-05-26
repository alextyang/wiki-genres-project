-- 0014_genre_youtube_playlists.sql
--
-- Manually curated public listening examples for a genre. This intentionally
-- stores only the genre link, playlist order, song title, artist, and YouTube
-- URL; discovery/ranking metadata belongs outside this table.

begin;

create table if not exists wg_genre_youtube_playlist_tracks (
    genre_id    text not null references wg_genres(id) on delete cascade,
    ordinal     integer not null,
    song_title  text not null,
    artist      text not null,
    youtube_url text not null,
    primary key (genre_id, ordinal),
    constraint wg_genre_youtube_playlist_tracks_ordinal_nonnegative
        check (ordinal >= 0),
    constraint wg_genre_youtube_playlist_tracks_title_nonempty
        check (length(btrim(song_title)) > 0),
    constraint wg_genre_youtube_playlist_tracks_artist_nonempty
        check (length(btrim(artist)) > 0),
    constraint wg_genre_youtube_playlist_tracks_youtube_url_valid
        check (youtube_url ~* '^https?://(www\.)?(youtube\.com|youtu\.be)/')
);

create unique index if not exists wg_genre_youtube_playlist_tracks_url_unique
    on wg_genre_youtube_playlist_tracks(genre_id, youtube_url);

commit;
