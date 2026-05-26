# wiki-genres

A continuously-synced mirror of Wikipedia's music-genre graph, exposed as a public REST API.

For every music genre with a Wikipedia `{{Infobox music genre}}` article, we capture structured edges (`subgenre`, `derivative`, `stylistic_origin`, …), aliases, instruments, origin metadata, and Wikidata cross-references — kept in sync with upstream via a weekly crawl.

**Data licence:** Wikipedia content is [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Code is MIT. Genre-bearing API responses include the source Wikipedia URL.

---

## API

All endpoints return JSON. No authentication required. Rate limit: 60 requests/minute per IP.

The graph explorer is served at `/explorer` and the site root redirects there.
Interactive API docs are served at `/docs` (Swagger UI) and `/redoc`.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/genres` | Paginated genre list. Filters: `q=`, `has_infobox=`, `updated_since=`. |
| `GET` | `/v1/genres/{id}` | Full genre detail with all edges, aliases, origins, instruments. |
| `GET` | `/v1/genres/{id}/playlist` | Manually curated YouTube playlist entries for a genre. |
| `GET` | `/v1/genres/{id}/edges` | Filtered edges. Params: `relation=`, `direction=out\|in\|both`. |
| `GET` | `/v1/genres/{id}/neighbors` | BFS graph expansion up to `depth=` hops (max 3). |
| `GET` | `/v1/resolve` | Resolve an alias, title, or QID to a canonical genre. Params: `title=`, `alias=`, `qid=`. |
| `GET` | `/v1/search` | Full-text search over titles, aliases, and summaries. Param: `q=`. |
| `GET` | `/v1/diff` | Genres changed since a timestamp. Param: `since=` (ISO 8601). Powers incremental consumer sync. |
| `GET` | `/v1/stats` | Node/edge counts, last sync timestamps, snapshot history. |
| `GET` | `/healthz` | Liveness probe. |
| `GET` | `/readyz` | Readiness probe (checks DB connectivity). |

### Examples

```bash
# Get a genre by internal ID (wg-{qid})
curl https://wiki-genres.example.com/v1/genres/wg-q188450

# Resolve an alias
curl "https://wiki-genres.example.com/v1/resolve?alias=EDM"

# Find stylistic origins
curl "https://wiki-genres.example.com/v1/genres/wg-q188450/edges?relation=stylistic_origin"

# Full-text search
curl "https://wiki-genres.example.com/v1/search?q=hyperpop"

# Incremental sync — genres changed since a date
curl "https://wiki-genres.example.com/v1/diff?since=2026-05-01T00:00:00Z"
```

### Edge relation vocabulary

| `relation` | Source | Direction |
|---|---|---|
| `subgenre` | infobox | parent → child |
| `derivative` | infobox | earlier → later |
| `stylistic_origin` | infobox | newer ← older |
| `cultural_origin` | infobox | genre → culture |
| `fusion_genre` | infobox | both |
| `regional_scene` | infobox | genre → place |
| `influenced_by` | Wikidata P737 | newer ← older |
| `subclass_of` | Wikidata P279 | specific → general |
| `part_of` | Wikidata P361 | child → parent |
| `instance_of` | Wikidata P31 | instance → class |

---

## Running locally

**Prerequisites:** Docker, Python 3.12+, [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/alextyang/wiki-genres-project
cd wiki-genres-project
cp .env.example .env

# Start Postgres
make db-up

# Install Python deps
make install

# Apply schema migrations
make migrate

# Populate the DB (~15–30 min; crawls ~5k Wikipedia genre pages)
make bootstrap

# Apply manual curation and derived relationship indexes
make curate
make rebuild-indexes

# Start the API
make api
# → http://localhost:8080/explorer
# → http://localhost:8080/docs
```

### Weekly sync (keep data fresh)

```bash
make sync
make curate
make rebuild-indexes
```

### Manual YouTube playlists

Genre pages can have a small, manually curated YouTube playlist. The database
stores only the genre id, playlist order, song title, artist, and YouTube URL.

Add one track:

```bash
wiki-genres playlist-add wg-q188450 \
  --title "Example Song" \
  --artist "Example Artist" \
  --youtube-url "https://www.youtube.com/watch?v=..."
```

Or import a CSV with these headers:

```csv
genre_id,song_title,artist,youtube_url,ordinal
wg-q188450,Example Song,Example Artist,https://www.youtube.com/watch?v=...,0
```

```bash
wiki-genres playlist-import ./genre-playlists.csv --replace-genres
wiki-genres playlist-list wg-q188450
```

Or schedule it via system cron (runs every Sunday at 06:00 UTC):

```cron
0 6 * * 0  cd /path/to/wiki-genres-project && docker compose run --rm api wiki-genres sync
```

### Data curation and discovery

The public graph intentionally excludes fetched pages that are not approved
music genre/style entries. Reapply that filter after any crawl:

```bash
wiki-genres curate-genres
```

For broader pages that may contain genre links, such as country music overview
pages, crawl the page links through the same strict classifier:

```bash
wiki-genres crawl-page-links \
  "Music of Vanuatu" \
  "Music of the Bahamas" \
  --max-links-per-page 300 \
  --concurrency 4
```

If a source page yields no approved genre links, the command marks that source
page as non-genre again by default. Then rebuild all derived graph indexes:

```bash
wiki-genres index-inbound-relationships --sample 0
wiki-genres flag-circular-relationships --sample 0
wiki-genres index-music-reachability --sample 0
```

`index-music-reachability` treats approved `Music of ...` pages as hidden
children of the synthetic `Music` root (`parent_source=music_country_root`).
This supports map-based navigation without exposing every country page as a
normal visible child in the explorer.

`curate-genres` also reapplies the small set of manual display edges in
`wiki_genres.curation`. These are reserved for high-confidence top-level
coverage gaps and regional `Music of ...` mounts, and are stored with
`source=manual_curation` so they remain auditable apart from upstream
Wikipedia/Wikidata facts.

---

## Development

```bash
make test       # run tests
make lint       # ruff check
make fmt        # ruff format + autofix
make typecheck  # mypy
```

Parser and loader tests use in-memory fixtures — no database required.

---

## Architecture

```
                Wikipedia API + Wikidata API
                          │
                 ┌────────▼────────┐
                 │   bootstrap /   │  on-demand: initial fill or rebuild
                 │   weekly sync   │  cron: SPARQL diff + stale refresh
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │    Postgres     │  wg_genres, wg_edges, wg_aliases, …
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │   FastAPI API   │  /v1/genres, /v1/search, /v1/diff, …
                 └─────────────────┘
```

The sync job runs the same fetch → parse → load pipeline as the bootstrap:
1. Re-run the Wikidata SPARQL seed query; enqueue any new QIDs not in our DB.
2. Enqueue genres whose `last_fetched_at` is older than `SYNC_STALENESS_DAYS` (default 7 days).
3. Drain the frontier (concurrent fetch + parse + load).
4. Re-resolve unresolved edges.
5. Write a `wg_snapshots` summary.

---

## Contributing

Issues and PRs welcome. Before a large change, open an issue to discuss scope.

- Code style: `ruff` (enforced in CI).
- Tests: add a test for any new parser behaviour.
- Data licensing: any code that outputs Wikipedia content must preserve the `wikipedia_url` attribution field in API responses.

---

## Licence

Code: [MIT](LICENSE).  
Data served by the API derives from Wikipedia ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)) and Wikidata ([CC0](https://creativecommons.org/publicdomain/zero/1.0/)).
