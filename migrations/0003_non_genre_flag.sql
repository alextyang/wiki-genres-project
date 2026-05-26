-- 0003_non_genre_flag.sql
--
-- Mark rows that were fetched during discovery but are not approved music
-- genre/style entries. This is intentionally separate from deleted_at, which
-- tracks upstream deletion rather than local curation.

begin;

alter table wg_genres
    add column is_non_genre boolean not null default false,
    add column non_genre_reviewed_at timestamptz,
    add column non_genre_review_note text;

create index wg_genres_non_genre_idx
    on wg_genres(is_non_genre)
    where is_non_genre;

commit;
