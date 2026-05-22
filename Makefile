.PHONY: help install db-up db-down db-reset migrate api lint typecheck test fmt

help:
	@echo "Common targets:"
	@echo "  install     install Python deps via uv"
	@echo "  db-up       start the dev postgres"
	@echo "  db-down     stop the dev postgres"
	@echo "  db-reset    drop the dev postgres volume and restart"
	@echo "  migrate     run alembic migrations against the dev postgres"
	@echo "  api         run the FastAPI dev server"
	@echo "  lint        run ruff"
	@echo "  typecheck   run mypy"
	@echo "  test        run pytest"
	@echo "  fmt         run ruff format"

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
	uv run alembic upgrade head

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
