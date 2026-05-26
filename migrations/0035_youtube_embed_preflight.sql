-- 0035_youtube_embed_preflight.sql
--
-- Stores whether a given YouTube URL is embeddable (public iframe playback).
-- This is used to skip "Video unavailable" entries when constructing a
-- 25-track public playlist per genre, while preserving failures for review.

begin;

create table if not exists wg_youtube_embed_preflight_cache (
    youtube_url   text primary key,
    is_embeddable boolean not null,
    checked_at    timestamptz not null default now(),
    http_status   integer,
    error         text,
    oembed_title  text,
    oembed_author text
);

create index if not exists wg_youtube_embed_preflight_cache_checked_at
    on wg_youtube_embed_preflight_cache(checked_at desc);

alter table if exists wg_genre_youtube_playlist_tracks
    add column if not exists is_embeddable boolean;

alter table if exists wg_genre_youtube_playlist_tracks
    add column if not exists embed_checked_at timestamptz;

alter table if exists wg_genre_youtube_playlist_tracks
    add column if not exists embed_http_status integer;

alter table if exists wg_genre_youtube_playlist_tracks
    add column if not exists embed_error text;

create index if not exists wg_genre_youtube_playlist_tracks_embeddable
    on wg_genre_youtube_playlist_tracks(genre_id, is_embeddable);

commit;

