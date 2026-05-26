.PHONY: help install db-up db-down db-reset migrate bootstrap sync api lint typecheck test fmt curate index-inbound flag-cycles index-reachability index-colors rebuild-indexes

help:
	@echo "Common targets:"
	@echo "  install     install Python deps (uv sync)"
	@echo "  db-up       start the dev postgres"
	@echo "  db-down     stop the dev postgres"
	@echo "  db-reset    drop the dev postgres volume and restart"
	@echo "  migrate     apply SQL migrations to the dev database"
	@echo "  bootstrap   run the full bootstrap crawl (populates DB from scratch)"
	@echo "  sync        run the weekly sync job manually"
	@echo "  curate      reapply the strict approved-genre filter"
	@echo "  rebuild-indexes rebuild inbound, cycle, reachability, and color indexes"
	@echo "  api         run the FastAPI dev server (hot-reload)"
	@echo "  lint        run ruff"
	@echo "  typecheck   run mypy"
	@echo "  test        run pytest"
	@echo "  fmt         format with ruff"

install:
	uv sync --extra dev

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d postgres

migrate:
	uv run wiki-genres migrate

bootstrap:
	uv run wiki-genres bootstrap --log-format pretty

sync:
	uv run wiki-genres sync --log-format pretty

curate:
	uv run wiki-genres curate-genres --log-format pretty

index-inbound:
	uv run wiki-genres index-inbound-relationships --sample 0 --log-format pretty

flag-cycles:
	uv run wiki-genres flag-circular-relationships --sample 0 --log-format pretty

index-reachability:
	uv run wiki-genres index-music-reachability --sample 0 --log-format pretty

index-colors:
	uv run wiki-genres index-genre-colors --sample 0 --log-format pretty

rebuild-indexes: index-inbound flag-cycles index-reachability index-colors

api:
	uv run uvicorn wiki_genres.api.main:app --reload --host 0.0.0.0 --port 8080

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest

fmt:
	uv run ruff format .
	uv run ruff check --fix .
