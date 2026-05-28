-- 0043_approved_playlist_warehouse.sql
--
-- Normalized production storage for manually approved provider playlists and
-- their full track lists. This keeps candidate/review data out of the
-- client-facing wg_genre_youtube_playlist_tracks table while allowing approved
-- playlist tracks to be stored once per provider playlist.

begin;

create table if not exists wg_provider_playlists (
    provider                 text not null,
    playlist_id              text not null,
    playlist_url             text,
    playlist_title           text,
    owner_name               text,
    total_tracks             integer,
    source_playlist_batch_id text,
    fetched_at               timestamptz,
    imported_at              timestamptz not null default now(),
    primary key (provider, playlist_id),
    constraint wg_provider_playlists_provider_nonempty
        check (length(btrim(provider)) > 0),
    constraint wg_provider_playlists_playlist_id_nonempty
        check (length(btrim(playlist_id)) > 0)
);

create table if not exists wg_provider_playlist_tracks (
    provider                 text not null,
    playlist_id              text not null,
    track_rank               integer not null,
    provider_track_id        text,
    video_id                 text,
    song_title               text not null,
    artists_json             jsonb not null default '[]'::jsonb,
    artist_display           text,
    album_name               text,
    duration_seconds         double precision,
    duration_ms              integer,
    popularity               integer,
    provider_url             text,
    source_playlist_batch_id text,
    fetched_at               timestamptz,
    imported_at              timestamptz not null default now(),
    primary key (provider, playlist_id, track_rank),
    constraint wg_provider_playlist_tracks_rank_nonnegative
        check (track_rank >= 0),
    constraint wg_provider_playlist_tracks_title_nonempty
        check (length(btrim(song_title)) > 0),
    foreign key (provider, playlist_id)
        references wg_provider_playlists(provider, playlist_id)
        on delete cascade
);

create index if not exists wg_provider_playlist_tracks_video_id
    on wg_provider_playlist_tracks(video_id)
    where video_id is not null;

create table if not exists wg_genre_approved_playlists (
    approval_uid             text primary key,
    decision_batch_id        text not null,
    playlist_discovery_group text not null,
    genre_id                 text not null references wg_genres(id) on delete cascade,
    provider                 text not null,
    playlist_id              text not null,
    ordinal                  integer not null default 0,
    confidence               double precision,
    policy                   text not null default 'playlist',
    source_playlist_batch_id text,
    imported_at              timestamptz not null default now(),
    constraint wg_genre_approved_playlists_ordinal_nonnegative
        check (ordinal >= 0),
    constraint wg_genre_approved_playlists_confidence_range
        check (confidence is null or (confidence >= 0 and confidence <= 1)),
    unique (decision_batch_id, genre_id, provider, playlist_id),
    foreign key (provider, playlist_id)
        references wg_provider_playlists(provider, playlist_id)
        on delete cascade
);

create index if not exists wg_genre_approved_playlists_genre
    on wg_genre_approved_playlists(genre_id, ordinal);

create index if not exists wg_genre_approved_playlists_group
    on wg_genre_approved_playlists(playlist_discovery_group, genre_id);

create or replace view wg_genre_approved_playlist_tracks as
select
    approved.approval_uid,
    approved.decision_batch_id,
    approved.playlist_discovery_group,
    approved.genre_id,
    approved.ordinal as playlist_ordinal,
    approved.confidence,
    approved.policy,
    playlist.provider,
    playlist.playlist_id,
    playlist.playlist_url,
    playlist.playlist_title,
    playlist.owner_name,
    track.track_rank,
    track.provider_track_id,
    track.video_id,
    track.song_title,
    track.artists_json,
    track.artist_display,
    track.album_name,
    track.duration_seconds,
    track.duration_ms,
    track.popularity,
    track.provider_url,
    track.source_playlist_batch_id,
    track.fetched_at,
    track.imported_at
from wg_genre_approved_playlists approved
join wg_provider_playlists playlist
  on playlist.provider = approved.provider
 and playlist.playlist_id = approved.playlist_id
join wg_provider_playlist_tracks track
  on track.provider = approved.provider
 and track.playlist_id = approved.playlist_id;

commit;
