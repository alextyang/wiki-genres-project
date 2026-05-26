-- 0004_curate_non_genres.sql
--
-- Freeze the current post-bootstrap review: keep the strict positive
-- music-genre classifier plus the manually approved no-infobox music
-- styles/forms below, and flag every other discovered row as non-genre.

begin;

create temporary table wg_manual_approved_titles (
    wikipedia_title text primary key
) on commit drop;

insert into wg_manual_approved_titles (wikipedia_title) values
    ('Ahwash n tferkhin'),
    ('Alap'),
    ('Alternative Joropo'),
    ('Arabic maqam'),
    ('Arrochadeira'),
    ('Ayacuchan Carnival'),
    ('Bajidor'),
    ('Ballad'),
    ('Battlemix'),
    ('Batuque (Brazil)'),
    ('Biguine ka'),
    ('Biguine vidé'),
    ('Boliyan'),
    ('Booty bass'),
    ('Breakbeat Kota'),
    ('British folk revival'),
    ('Burru'),
    ('Caipira samba'),
    ('Chalupa (music)'),
    ('Chanson éxotique'),
    ('Charanga (Cuba)'),
    ('Chicha music'),
    ('Chilean cumbia'),
    ('Chinese yellow music'),
    ('Chunchaca'),
    ('Coastal taarab'),
    ('Colour house'),
    ('Creole Joropo'),
    ('Dangdut House'),
    ('Dangdut bumbung'),
    ('Dangdut dendang saluang'),
    ('Dangdut electro'),
    ('Dangdut gondang'),
    ('Dangdut jaipong'),
    ('Dangdut kalimantan'),
    ('Dangdut pantura'),
    ('Dangdut rampak'),
    ('Dangdut tarling'),
    ('Devotional song'),
    ('Edo Highlife'),
    ('Electro trance'),
    ('Embolada'),
    ('Estrada'),
    ('Euro deep house (genre)'),
    ('Flint rap'),
    ('Full bass'),
    ('Grand chant'),
    ('Hiyawa'),
    ('Honky-tonk'),
    ('Ijaw Highlife'),
    ('Impressionism in music'),
    ('Jhala'),
    ('Juju'),
    ('Leammt'),
    ('Malagueñas (flamenco style)'),
    ('Milonga candombe'),
    ('Music of Antigua and Barbuda'),
    ('Music of Barbados'),
    ('Music of Dominica'),
    ('Music of Eswatini'),
    ('Music of Grenada'),
    ('Music of Kiribati'),
    ('Music of Montenegro'),
    ('Music of Northern Cyprus'),
    ('Music of South Sudan'),
    ('Music of the Bahamas'),
    ('Music of the Cook Islands'),
    ('Music of the Federated States of Micronesia'),
    ('Music of the Marshall Islands'),
    ('Music of the United Arab Emirates'),
    ('Music of Tokelau'),
    ('Music of Tuvalu'),
    ('Music of Vanuatu'),
    ('Muzak'),
    ('Neoclassicism (music)'),
    ('Nyabinghi rhythm'),
    ('Operetta'),
    ('Peak time techno'),
    ('Psy-tech trance'),
    ('Rare groove'),
    ('Rhythmic adult contemporary'),
    ('Romantic Joropo'),
    ('Samba duro'),
    ('Scat singing'),
    ('Soleá'),
    ('Soundtrack'),
    ('Spoken word'),
    ('Straight edge'),
    ('String band'),
    ('Tagonggo'),
    ('Tala (music)'),
    ('Tango'),
    ('Tango (flamenco)'),
    ('Tientos (flamenco)'),
    ('Toasting (Jamaican music)'),
    ('Tuk band'),
    ('Turkish makam'),
    ('Urban adult contemporary'),
    ('Valse musette'),
    ('Vaneira'),
    ('Verdiales'),
    ('Vocal jazz'),
    ('Waltz'),
    ('Zambapalo'),
    ('Zarzuela');

create temporary table wg_approved_genre_ids on commit drop as
select g.id
from wg_genres g
where g.has_infobox
   or exists (
        select 1
        from wg_edges e
        where e.from_genre_id = g.id
          and e.source = 'wikidata'
          and e.relation in ('instance_of', 'subclass_of')
          and e.to_raw_label in ('Q188451', 'Q2944929')
   )
   or exists (
        select 1
        from wg_categories c
        where c.genre_id = g.id
          and c.category ilike any(array[
              '%music genre%',
              '%music genres%',
              '%musical genre%',
              '%musical genres%',
              '%music style%',
              '%music styles%',
              '%musical style%',
              '%musical styles%',
              '%styles of music%'
          ])
   )
   or exists (
        select 1
        from wg_manual_approved_titles t
        where t.wikipedia_title = g.wikipedia_title
   );

update wg_genres g
set is_non_genre = not exists (
        select 1 from wg_approved_genre_ids a where a.id = g.id
    ),
    non_genre_reviewed_at = case
        when exists (select 1 from wg_approved_genre_ids a where a.id = g.id)
        then null
        else now()
    end,
    non_genre_review_note = case
        when exists (select 1 from wg_approved_genre_ids a where a.id = g.id)
        then null
        else 'manual review: not an approved music genre/style entry'
    end;

insert into wg_snapshots (
    id, kind, started_at, finished_at, nodes_total, edges_total, notes
)
select
    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
        || '-manual-curation',
    'reconciler',
    now(),
    now(),
    (select count(*) from wg_genres where is_non_genre = false and deleted_at is null),
    (
        select count(*)
        from wg_edges e
        join wg_genres from_g on from_g.id = e.from_genre_id
        left join wg_genres to_g on to_g.id = e.to_genre_id
        where from_g.is_non_genre = false
          and from_g.deleted_at is null
          and (
            e.to_genre_id is null
            or (to_g.is_non_genre = false and to_g.deleted_at is null)
          )
    ),
    'Manual genre approval pass. Non-approved discovered rows flagged is_non_genre.'
on conflict (id) do nothing;

commit;
