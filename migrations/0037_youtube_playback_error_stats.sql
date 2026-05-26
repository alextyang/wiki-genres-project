-- 0037_youtube_playback_error_stats.sql
--
-- Client-observed YouTube iframe playback failures. These are runtime signals
-- from the public player, used to rank repeatedly failing videos later.

begin;

create table if not exists wg_youtube_playback_error_stats (
    genre_id       text not null references wg_genres(id) on delete cascade,
    youtube_url    text not null,
    error_count    integer not null default 0,
    first_seen_at  timestamptz not null default now(),
    last_seen_at   timestamptz not null default now(),
    last_error     text,
    last_title     text,
    last_artist    text,
    last_page_url  text,
    primary key (genre_id, youtube_url),
    constraint wg_youtube_playback_error_stats_count_nonnegative
        check (error_count >= 0)
);

create index if not exists wg_youtube_playback_error_stats_genre_count
    on wg_youtube_playback_error_stats(genre_id, error_count desc, last_seen_at desc);

commit;

