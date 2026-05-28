-- 0044_approved_playlist_client_view_drop_legacy.sql
--
-- Expose normalized approved playlist tracks through the legacy client contract,
-- filtering known YouTube 150 playback failures, then drop the archived legacy
-- flat playlist table.

begin;

create or replace view wg_genre_approved_client_playlist_tracks as
with normalized_tracks as (
    select
        tracks.genre_id,
        tracks.playlist_ordinal,
        tracks.track_rank,
        tracks.song_title,
        coalesce(nullif(tracks.artist_display, ''), '') as artist,
        case
            when nullif(tracks.video_id, '') is not null
                then 'https://www.youtube.com/watch?v=' || tracks.video_id
            else tracks.provider_url
        end as youtube_url,
        tracks.provider_url,
        tracks.video_id
    from wg_genre_approved_playlist_tracks tracks
    where tracks.provider_url is not null
),
blocked_tracks as (
    select distinct
        errors.genre_id,
        coalesce(
            nullif(substring(errors.youtube_url from '[?&]v=([^&]+)'), ''),
            errors.youtube_url
        ) as youtube_key
    from wg_youtube_playback_error_stats errors
    where errors.last_error = '150'
),
playable_tracks as (
    select tracks.*
    from normalized_tracks tracks
    left join blocked_tracks blocked
      on blocked.genre_id = tracks.genre_id
     and (
         blocked.youtube_key = tracks.youtube_url
         or blocked.youtube_key = tracks.provider_url
         or (
             tracks.video_id is not null
             and blocked.youtube_key = tracks.video_id
         )
     )
    where blocked.genre_id is null
)
select
    tracks.genre_id,
    (row_number() over (
        partition by tracks.genre_id
        order by
            tracks.playlist_ordinal,
            tracks.track_rank,
            tracks.artist,
            tracks.song_title,
            tracks.youtube_url
    ) - 1)::integer as ordinal,
    tracks.song_title,
    tracks.artist,
    tracks.youtube_url
from playable_tracks tracks;

drop table if exists wg_genre_youtube_playlist_tracks;

commit;
