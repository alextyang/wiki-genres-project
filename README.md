# wiki-genres

A continuously-synced public mirror of the music-genre graph encoded in Wikipedia + Wikidata, served over a stable HTTP API.

> **Status:** v0, pre-alpha. The repo is scaffolding only — see [docs/PLAN.md](docs/PLAN.md) for the full design and current roadmap.

---

## What this is

For every Wikipedia article that carries `{{Infobox music genre}}`, we record:

- The canonical title, Wikidata Q-ID, and redirects pointing at it.
- All synonyms (`other_names`) and Wikidata aliases.
- Typed edges to other genres: `subgenre`, `derivative`, `stylistic_origin`, `fusion_genre`, `regional_scene`, `local_scene`, `other_name`, plus Wikidata's `influenced_by`, `subclass_of`, `part_of`, `instance_of`.
- Cultural and temporal origins, instruments, infobox color, and the article's lead summary.

The graph is rebuilt continuously from Wikimedia's [EventStreams](https://stream.wikimedia.org/?doc) and a nightly Wikidata SPARQL diff. It is exposed as a JSON HTTP API.

## What this isn't

- An editorialised or curated taxonomy. We mirror Wikipedia faithfully, errors and all.
- A music recommender. Out of scope.
- Multilingual. English Wikipedia only in v1.

## Quick start (once M1 lands — not yet)

```bash
git clone https://github.com/koopakondra/wiki-genres-project.git
cd wiki-genres-project
cp .env.example .env
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run wiki-genres bootstrap            # ~30 min initial crawl
uv run uvicorn wiki_genres.api.main:app --reload
curl http://localhost:8080/v1/genres/electro
```

## Project layout

See [docs/PLAN.md § Appendix A](docs/PLAN.md#appendix-a--file-layout-target) for the target layout. Current state is scaffolding; most directories are empty.

## License

Code: [MIT](LICENSE).

Data exposed by the API derives from Wikipedia, which is licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). API responses include attribution to the source article on every record; consumers redistributing the data must comply with CC BY-SA.

## Contributing

Not yet open for outside contributions while the schema is still in flux. Once M2 ships, see `CONTRIBUTING.md` (to be written).
