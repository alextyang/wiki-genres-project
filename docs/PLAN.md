# wiki-genres: a continuously-synced mirror of Wikipedia's music-genre graph

**Status:** v0 design doc. Reflects intent, not the current state of the codebase.
**Last revised:** 2026-05-21
**Owner:** koopakondra

This document is the canonical plan for the project. Code-level decisions live in `docs/adr/`.

---

## 1. Mission

Build a public, openly-licensed mirror of the music-genre graph encoded in Wikipedia + Wikidata, kept continuously in sync with upstream, and expose it as a stable HTTP API.

The first consumer is [active-listener](https://github.com/koopakondra/active-listener), but the project is designed to stand alone — anyone working on music taxonomy, recommendation, journalism, or research should be able to point at our API or run their own copy.

### What "music-genre graph" means here

For every music genre that has a Wikipedia article with `{{Infobox music genre}}`, we capture:

- **Identity** — Wikidata Q-ID, canonical title, redirects, language sitelinks.
- **Aliases / synonyms** — the infobox `other_names` field plus Wikidata aliases.
- **Typed edges** — `subgenre`, `derivative`, `stylistic_origin`, `cultural_origin`, `fusion_genre`, `regional_scene`, `local_scene`, `influenced_by`, `subclass_of`, `part_of`.
- **Origin context** — cultural and temporal origin strings, with best-effort parsed year/region.
- **Instruments**, **categories**, **infobox color**, lead-paragraph summary.
- **Provenance** — for every fact: source (`infobox` vs `wikidata`), fetch timestamp, content hash.

### What we are *not* building

- An editorialised or curated taxonomy. We mirror Wikipedia faithfully, including its mistakes and biases. Curation happens downstream (in active-listener's `BROADER_TAG_RELATIONS` and similar layers).
- A multilingual graph in v1. English Wikipedia + Wikidata only; sitelinks recorded but other-language pages not parsed.
- A music-recommendation engine, similarity search, or embeddings store. Out of scope.

---

## 2. Why a separate public service

The previous iteration of this plan embedded the crawler inside active-listener as a one-shot manual script. Three reasons it deserves its own home:

1. **Cadence mismatch.** Wikipedia edits this graph constantly. A one-shot snapshot is stale within weeks. A weekly re-sync amortises the engineering cost across every downstream consumer and keeps the data fresh without operator intervention.
2. **Reusability.** The graph is interesting beyond active-listener — to anyone doing music software, journalism, or research. Making it public turns sunk effort into shared infrastructure.
3. **Operational separation.** Even a small weekly sync job has different failure modes than a music app. Letting it fail independently keeps active-listener's runtime simple.

The trade-off is one more service to operate. Mitigated by co-locating it on the same VM as active-listener (see §8) and keeping the surface area minimal — a single API process plus a weekly cron job.

### 2.1 Why weekly, not real-time?

Music-genre articles change slowly. New genres appear, infobox tweaks happen, but the underlying graph is fairly stable week-to-week. Downstream consumers (a music player tagging tracks) tolerate week-old data without any user-visible degradation. Real-time sync (Wikipedia EventStreams) would require a persistent SSE subscriber, cursor management, a frontier worker pool, and reconnect logic — all to lower latency from days to seconds for data nobody needs in seconds. Skipped.

---

## 3. Architecture overview

```
                  ┌─────────────────────────────────────┐
                  │       UPSTREAM (Wikimedia)          │
                  │  ┌─────────────┐  ┌──────────────┐  │
                  │  │ en.wiki API │  │ Wikidata API │  │
                  │  └──────┬──────┘  └──────┬───────┘  │
                  └─────────┼─────────────────┼──────────┘
                            │                 │
              ╔═════════════▼═════════════════▼═══════════════╗
              ║                                                ║
              ║   wiki-genres service (single VM, dockerised)  ║
              ║                                                ║
              ║   ┌────────────────┐                           ║
              ║   │  api (FastAPI) │   ◄── always-on, reads    ║
              ║   │   - /genres    │                           ║
              ║   │   - /search    │                           ║
              ║   │   - /diff      │                           ║
              ║   │   - /healthz   │                           ║
              ║   └───────┬────────┘                           ║
              ║           │                                    ║
              ║           ▼                                    ║
              ║   ┌─────────────────────────────────────────┐  ║
              ║   │        Postgres (graph + log)           │  ║
              ║   └────────────────────┬────────────────────┘  ║
              ║                        ▲                       ║
              ║                        │                       ║
              ║   ┌────────────────────┴────────────────────┐  ║
              ║   │  weekly sync (cron, one-shot per run)   │  ║
              ║   │   1. SPARQL: find new genres            │  ║
              ║   │   2. Refetch pages with stale data      │  ║
              ║   │   3. Re-resolve unresolved edges        │  ║
              ║   │   4. Write snapshot diff                │  ║
              ║   └─────────────────────────────────────────┘  ║
              ║                                                ║
              ║   ┌──────────────────┐                         ║
              ║   │ bootstrap / cli  │   ◄── on-demand only    ║
              ║   └──────────────────┘                         ║
              ╚════════════════════════════════════════════════╝
                              │
                              ▼
                      ┌─────────────────┐
                      │    consumers    │
                      │ active-listener │
                      │   others...     │
                      └─────────────────┘
```

Two long-running pieces and a weekly cron — that's the entire system:

| Process | Purpose | Long-running? |
|---|---|---|
| `api` | Public HTTP API. Read-only over the graph. | Yes (FastAPI/uvicorn). |
| `sync` | Weekly job: SPARQL seed diff → refetch stale pages → resolve edges → snapshot. | No (one-shot, cron-driven). |
| `bootstrap` | Full crawl from seed set. Idempotent. Used for initial fill, or to rebuild from scratch. | No (run on demand). |
| `cli` | Operator interface — inspect frontier, kick a refetch, print stats. | No. |

All four share one library (`src/wiki_genres/`). Different entry points; same code. The weekly sync is literally a `bootstrap` invocation with a staleness filter — same fetcher, same parser, same loader.

---

## 4. Data model

Postgres schema lives in `migrations/`. Names prefixed `wg_` (wiki-genres) and chosen to be self-contained — this DB doesn't know or care about active-listener.

### 4.1 Core tables

```sql
wg_genres (
    id                  text primary key,        -- stable internal id: slug derived from QID
    wikidata_qid        text unique,             -- "Q188450"; nullable if no wikidata entry
    wikipedia_title     text not null unique,    -- post-redirect canonical title
    wikipedia_url       text not null,
    summary             text,                    -- first paragraph plain text
    infobox_color       text,                    -- #RRGGBB if present
    is_seed             boolean not null default false,
    has_infobox         boolean not null default false,
    raw_wikitext_sha256 text,
    first_seen_at       timestamptz not null,
    last_fetched_at     timestamptz not null,
    last_changed_at     timestamptz not null,    -- when our local copy meaningfully changed
    upstream_revision   bigint,                  -- Wikipedia revision id
    deleted_at          timestamptz              -- soft-delete on upstream deletion
)

wg_redirects (
    from_title          text primary key,
    to_genre_id         text not null references wg_genres(id) on delete cascade,
    first_seen_at       timestamptz not null
)

wg_aliases (
    genre_id            text not null references wg_genres(id) on delete cascade,
    alias               text not null,
    source              text not null,           -- 'other_names' | 'wikidata_alias' | 'redirect'
    first_seen_at       timestamptz not null,
    primary key (genre_id, alias, source)
)

wg_edges (
    from_genre_id       text not null references wg_genres(id) on delete cascade,
    to_genre_id         text references wg_genres(id) on delete cascade,
    to_raw_label        text not null,           -- preserved verbatim if to_genre_id unresolved
    relation            text not null,           -- see vocabulary below
    source              text not null,           -- 'infobox' | 'wikidata'
    ordinal             integer not null default 0,
    first_seen_at       timestamptz not null,
    primary key (from_genre_id, relation, source, ordinal),
    constraint wg_edges_relation_valid check (relation in (
        'subgenre', 'derivative', 'stylistic_origin', 'cultural_origin',
        'fusion_genre', 'regional_scene', 'local_scene', 'other_name',
        'influenced_by', 'subclass_of', 'part_of', 'instance_of'
    ))
)

wg_origins (
    genre_id            text not null references wg_genres(id) on delete cascade,
    kind                text not null,           -- 'cultural' | 'temporal'
    value               text not null,
    parsed_year_start   integer,
    parsed_year_end     integer,
    parsed_region       text,
    primary key (genre_id, kind, value)
)

wg_instruments (
    genre_id            text not null references wg_genres(id) on delete cascade,
    instrument          text not null,
    instrument_genre_id text references wg_genres(id) on delete set null,
    primary key (genre_id, instrument)
)

wg_categories (
    genre_id            text not null references wg_genres(id) on delete cascade,
    category            text not null,
    primary key (genre_id, category)
)
```

### 4.2 Sync & provenance tables

These exist *because* this is a continuously-syncing service.

```sql
wg_fetch_log (
    id                  bigserial primary key,
    url                 text not null,
    fetched_at          timestamptz not null,
    http_status         integer not null,
    content_sha256      text,
    elapsed_ms          integer,
    via                 text not null            -- 'bootstrap' | 'sync_worker' | 'manual'
)

wg_revisions (
    genre_id            text not null references wg_genres(id) on delete cascade,
    upstream_revision   bigint not null,
    fetched_at          timestamptz not null,
    content_sha256      text not null,
    triggered_by        text not null,           -- 'bootstrap' | 'sync' | 'manual'
    diff_summary        jsonb,                   -- {edges_added: 3, aliases_removed: 1, ...}
    primary key (genre_id, upstream_revision)
)

wg_frontier (
    title               text primary key,
    enqueued_at         timestamptz not null,
    not_before          timestamptz not null,    -- backoff support
    reason              text not null,           -- 'seed' | 'wikilink' | 'manual' | 'sync_stale' | 'sync_new'
    attempts            integer not null default 0
)

wg_sync_state (
    key                 text primary key,        -- 'last_sync_started_at', 'last_sync_finished_at', etc.
    value               jsonb not null,
    updated_at          timestamptz not null
)

wg_snapshots (
    id                  text primary key,        -- e.g. '2026-05-21T12:00:00Z-bootstrap'
    kind                text not null,           -- 'bootstrap' | 'dump_audit'
    started_at          timestamptz not null,
    finished_at         timestamptz,
    nodes_total         integer,
    edges_total         integer,
    notes               text
)
```

### 4.3 Edge relation vocabulary

| `relation` | Source | Direction |
|---|---|---|
| `subgenre` | infobox `subgenres` | `from` is the parent, `to` is the child |
| `derivative` | infobox `derivatives` | `from` led to `to` |
| `stylistic_origin` | infobox `stylistic_origins` | `from` emerged from `to` |
| `cultural_origin` | infobox `cultural_origins` (when wikilinked) | `from` emerged from `to`'s culture |
| `fusion_genre` | infobox `fusion_genres` | undirected pair (stored both ways) |
| `regional_scene` | infobox `regional_scenes` | `to` is a regional scene of `from` |
| `local_scene` | infobox `local_scenes` | `to` is a local scene of `from` |
| `other_name` | infobox `other_names` | `from` is also known as `to_raw_label` |
| `influenced_by` | Wikidata `P737` | `to` influenced `from` |
| `subclass_of` | Wikidata `P279` | `from` is a subclass of `to` |
| `part_of` | Wikidata `P361` | `from` is part of `to` |
| `instance_of` | Wikidata `P31` | `from` is an instance of `to` |

Both `infobox` and `wikidata` provenance are stored as separate rows even when they agree — consumers can pick one or both.

### 4.4 What "the same fact, observed twice" looks like

A bootstrap run finds `electro → electronic` from the infobox. Six months later, an editor adds `P279 electro subclass_of electronic_music` on Wikidata. Both rows exist in `wg_edges` keyed by `(from, relation, source, ordinal)`. Consumers union them; we never merge.

When the *same* infobox row gets re-fetched and produces identical content, nothing changes. When it produces different content, the old row is deleted and the new row written inside one transaction, and a `wg_revisions` entry records the diff.

---

## 5. Bootstrap pipeline

One-shot, idempotent, re-runnable. Lives in `src/wiki_genres/crawler/` + `parser/` + `loader/`.

### 5.1 Seeding

```sparql
SELECT DISTINCT ?genre ?genreLabel ?article WHERE {
  { ?genre wdt:P31 wd:Q188451 }      # instance of music genre
  UNION { ?genre wdt:P31 wd:Q2944929 }  # musical style
  UNION { ?genre wdt:P279+ wd:Q188451 }  # subclass-of-genre (closed under +)
  ?article schema:about ?genre ;
           schema:isPartOf <https://en.wikipedia.org/>.
  SERVICE wikibase:label { bd:serviceLabel "en". }
}
```

Yields ~3–5k seed (QID, en.wiki title) pairs. Cross-checked against `Category:Music_genres` and `List_of_music_genres` for safety.

### 5.2 Crawl

Single-process, async, polite:

- `httpx.AsyncClient` with semaphore = 4 concurrent requests (still ≤ 1 req/s/host effective with retry/backoff).
- `User-Agent: wiki-genres/<version> (https://github.com/koopakondra/wiki-genres-project; koopakondra@gmail.com)`.
- Retries with exponential backoff on 429/5xx; respect `Retry-After`.
- Every response logged to `wg_fetch_log` with SHA-256 of body.
- Raw wikitext + raw Wikidata JSON cached on disk under `.cache/{qid}/{revision}.{ext}` so a re-parse never re-crawls.

### 5.3 Parse

`mwparserfromhell` over wikitext. For each `Infobox music genre` template:

- Walk template parameters. For each parameter we care about (`subgenres`, `derivatives`, etc.):
  - Collect `Wikilink` nodes in document order → `(target, display)` tuples.
  - Split residual plaintext on `<br>`, `;`, `•`, ` / `, and list-item markers; preserve order.
  - Stripping logic for `{{hlist}}`, `{{flatlist}}`, `{{plainlist}}`, `{{ublist}}`.
- `other_names` is split aggressively (commas and newlines) and deduplicated case-insensitively.
- `color_background` kept only if it matches `^#?[0-9A-Fa-f]{6}$` after stripping the `{{music genre color}}` wrapper.
- First paragraph of lead extracted via `parsoid HTML` (separate `prop=text` API call; cheaper than re-running parsoid locally).

### 5.4 Load

Two-pass, transactional per genre:

1. **Pass 1.** Insert/upsert all `wg_genres` rows + `wg_redirects`. No edges yet.
2. **Pass 2.** For each genre, resolve edge targets by:
   1. Direct title match against `wg_genres.wikipedia_title`.
   2. Redirect lookup via `wg_redirects`.
   3. Wikidata QID match for Wikidata-sourced edges.
   4. Leave `to_genre_id = NULL` and keep `to_raw_label` if all three miss.

Unresolved edges are re-resolved on every reconciler pass (§6.3) — they often become resolvable once the frontier expands.

---

## 6. Weekly sync

One job, runs on a cron, completes in minutes. Same code as the bootstrap pipeline (§5) — just invoked with a staleness filter and the existing seed query.

### 6.1 What the job does

1. **Discover new genres.** Re-run the seed SPARQL query (§5.1). Any QID not yet in `wg_genres` is enqueued onto `wg_frontier` with `reason='sync_new'`.
2. **Refresh stale pages.** Enqueue every genre whose `last_fetched_at` is older than the staleness budget (default 7 days) with `reason='sync_stale'`. This naturally amortises the load: ~700 fetches per weekly run for a ~5k-genre graph at a 7-day budget.
3. **Drain the frontier.** Same fetch + parse + load pipeline as the bootstrap. New pages get added; existing pages get diffed against the previous fetch and `wg_revisions` records the change.
4. **Re-resolve unresolved edges.** Run the pass-2 resolver (`resolve_edges`) — edges that previously had `to_genre_id IS NULL` may now resolve because new genres were just loaded.
5. **Write a snapshot.** Insert a `wg_snapshots` row summarising what changed (genres added/updated, edges added/removed, parse errors).

### 6.2 What it does *not* do

- **No real-time subscription.** Wikipedia EventStreams is out of scope. The latency cost (days, not seconds) is acceptable for the use case, and the operational cost (persistent SSE, cursor management, reconnect logic, a worker pool) is not.
- **No deletes from upstream.** A QID disappearing from the seed query does not delete the row — it sets `wg_genres.deleted_at = NULL` only after manual confirmation via the CLI. Wikidata reclassifications happen all the time and we'd rather keep stale data than lose it silently.

### 6.3 How it runs

Two equally good options; pick one operationally:

- **System cron** on the VM: `0 6 * * 0 docker compose run --rm wiki-genres sync` (Sundays 06:00 UTC). Simplest possible setup; the sync container exits when done. The `cron` daemon is the only scheduler.
- **APScheduler inside the API process**: same job triggered in-process. Avoids a second container, but couples the API's uptime to the sync schedule. Preferred only if the VM doesn't have cron.

Either way, the sync is a single invocation of `wiki-genres sync` (a new CLI command — see §10). It writes its progress to logs and `wg_sync_state`. If it crashes mid-run, the next invocation picks up where it left off (the frontier is durable).

### 6.4 Catching up after downtime

The sync has no built-in concept of "missed runs" because it doesn't need one. Whether it last ran 7 days or 30 days ago, the next invocation refetches the same pages — `wg_genres.last_fetched_at < now() - interval '7 days'` simply matches more rows after a longer gap. The frontier soaks up the work and processes it.

### 6.5 Optional: monthly dump audit

Wikipedia publishes complete XML dumps once a month. A dump-based variant of the bootstrap can audit our DB against the dump for full coverage (catching genres that drift in and out of the seed query). Not on the critical path; punted to post-launch.

---

## 7. API

REST, JSON, public by default. Designed to be cacheable.

### 7.1 Surface (v1)

| Method & path | Returns |
|---|---|
| `GET /v1/genres` | Paginated list. Query: `q=`, `has_infobox=`, `updated_since=`. |
| `GET /v1/genres/{id}` | Single genre with all edges, aliases, origins, instruments. |
| `GET /v1/genres/{id}/edges?relation=subgenre&direction=out` | Filtered edge list. |
| `GET /v1/genres/{id}/neighbors?depth=2` | BFS up to depth N for visualisations. |
| `GET /v1/resolve?alias=EDM` | Alias / redirect resolution. Returns the canonical genre. |
| `GET /v1/search?q=hyperpop` | Full-text search over titles, aliases, summaries. |
| `GET /v1/diff?since=2026-05-01` | Changes (genres + edges) since a timestamp. Powers incremental sync for consumers. |
| `GET /v1/stats` | Node/edge counts, last sync timestamps, snapshot history. |
| `GET /healthz`, `/readyz` | Liveness + readiness. |

### 7.2 Stability & versioning

- URLs versioned under `/v1/`. Breaking changes mean `/v2/` and a deprecation window of 6 months on `/v1/`.
- Response bodies are open for additive change without bumping the version.
- A consumer (e.g. active-listener) is expected to call `/v1/diff?since=...` on a schedule rather than re-fetching the world.

### 7.3 No auth on reads

Public, anonymous, rate-limited per IP (token bucket, e.g. 60 req/min). Writes (`POST /admin/refetch/{id}`, `POST /admin/reconcile`) require a static admin token from env.

### 7.4 Cacheability

- All `GET` responses include `ETag` + `Last-Modified` derived from `last_changed_at`.
- 7-day `max-age` on individual genre endpoints; consumers should still trust ETags for revalidation.
- `Cache-Control: no-store` on `/healthz`, `/v1/diff`, `/v1/stats`.

---

## 8. Operations

### 8.1 Deployment

Single VM, alongside active-listener. Containerised via `docker-compose.yml`:

```
services:
  postgres:    # own instance; shared with active-listener is an open question
  api:         # uvicorn, port 8080, behind nginx/Caddy. The only long-running container.
```

The weekly sync runs as a system cron job that invokes `docker compose run --rm api wiki-genres sync`. No always-on sync container.

Public DNS: `wiki-genres.<domain>` (to be decided). TLS via Caddy auto-cert or the existing active-listener TLS terminator.

### 8.2 Backups

- Postgres logical dump nightly to S3-compatible storage.
- Raw fetch cache (`.cache/`) is rebuildable from upstream and is **not** backed up.
- Migration files are the source of truth for schema.

### 8.3 Observability

- Structured JSON logs to stdout; collected by whatever's running on the VM.
- Per-process metrics over `/metrics` (Prometheus exposition format): fetch latency, parse errors per page, edges created/deleted per sync run, time since last successful sync.
- A simple `/v1/stats` endpoint on the public API for at-a-glance health (last sync timestamp, node/edge counts).
- Alert if `now() - last_successful_sync > 14 days` — two missed weekly runs.

### 8.4 Cost expectation

- ~5k pages × ~50 KB wikitext ≈ 250 MB raw, ≈ 50 MB parsed. Postgres footprint negligible.
- Egress: API responses are kilobyte-scale; even 1M req/month is sub-dollar bandwidth.
- The dominant ongoing cost is the VM itself, already paid for.

---

## 9. Integration with active-listener (deferred)

Not built in v0. Sketched here so the API shape stays compatible.

active-listener will:

1. On boot, pull `/v1/diff?since={local_high_water_mark}` and merge into a local read-replica table (`active_listener_wikipedia_genre_mirror`). Catches up incrementally.
2. Build a lookup `(normalized_label → wikipedia_genre_id)` by joining its own `active_listener_music_tags.slug` against `wg_aliases.alias` (lowercased).
3. Augment `BROADER_TAG_RELATIONS` in scoring.ts from `wg_edges` where `relation in ('subgenre', 'subclass_of')` — but hand-written entries always win as overrides.

The synonym question that started this — `edm-pop ↔ dance-pop` — becomes: are they `other_name` edges of one canonical genre? If so, both resolve to the same `wg_genres.id`, and active-listener treats them as a single tag.

---

## 10. Roadmap

| Milestone | Scope | Estimate |
|---|---|---|
| **M0 — scaffolding** *(done)* | Repo skeleton, schema migration, FastAPI shell, docker-compose, CI. No data yet. | ½ day |
| **M1 — bootstrap pipeline** *(done)* | Seed SPARQL, fetcher, mwparserfromhell parser, loader. Produces a populated DB end-to-end. | 3–4 days |
| **M2 — read API** | `GET /v1/genres/{id}`, `GET /v1/resolve`, `GET /v1/search`, `GET /v1/stats`. | 2 days |
| **M3 — weekly sync** | `wiki-genres sync` CLI command: SPARQL diff + stale refetch + edge resolve + snapshot. Cron entry. | 1–2 days |
| **M4 — diff API + consumer integration** | `GET /v1/diff?since=…`. active-listener pulls and integrates. | 2 days |
| **M5 — public launch** | README, contributing guide, CI on PRs, rate limiting, public DNS. | 1–2 days |

Total: ~2 weeks of focused work to v1 (down from ~3 with the original real-time architecture).

---

## 11. Risks & open questions

- **Infobox coverage.** If significantly < 90% of genre articles have `{{Infobox music genre}}`, we need a prose-fallback parser. Bootstrap will surface the true number; design a fallback only if needed.
- **Sync run duration.** A weekly run touches ~700 pages at ≤1 req/s/host → ~15 minutes per host, parallelised across en.wiki + wikidata. Comfortable margin. If the graph grows 10×, revisit.
- **Wikidata vs wikitext divergence.** Sometimes they disagree (e.g. Wikidata classifies "Electro" as a subgenre of "Electronic dance music"; the infobox says "Electronic"). We store both and let consumers pick. Documented behaviour, not a bug.
- **Cycles.** Common in this graph (fusion genres, sibling scenes). Schema permits them; consumers must be cycle-aware.
- **Shared vs separate Postgres** with active-listener — open. Shared is operationally simpler (one backup), but couples deploys and complicates open-sourcing the docker-compose. Default: separate instance, same VM.
- **Licensing for downstream content.** Wikipedia text is CC BY-SA; our schema and code are MIT; the *data* we expose carries the CC BY-SA obligation. The API response includes attribution and a link to the source article. Documented in the README and `/v1/genres/{id}` responses.
- **Naming.** Project name is `wiki-genres` for now. Open to a more memorable name before public launch.

---

## Appendix A — File layout (target)

```
wiki-genres-project/
├── README.md
├── LICENSE                          # MIT (code) + CC BY-SA notice (data)
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── .env.example
├── .gitignore
├── docs/
│   ├── PLAN.md                      # this file
│   ├── architecture.md
│   ├── schema.md
│   ├── api.md
│   ├── sync.md
│   ├── operations.md
│   └── adr/
│       ├── 0001-python-fastapi.md
│       ├── 0002-postgres-schema.md
│       ├── 0003-continuous-sync.md
│       └── 0004-public-licensing.md
├── migrations/
│   └── 0001_initial.sql
├── src/wiki_genres/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── cli.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── routes/
│   ├── crawler/      # fetcher, frontier, seeds, bootstrap (and weekly sync)
│   ├── parser/       # infobox + wikidata parsers
│   └── loader/       # two-pass loader, resolve_edges
├── tests/
└── scripts/
```
