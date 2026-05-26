FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

# Install uv for fast dependency installation.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and source before installing the local package.
COPY pyproject.toml .
COPY README.md .
COPY src/ src/
RUN uv pip install --system --no-cache .

# Copy runtime SQL migrations.
COPY migrations/ migrations/

# Run migrations then start the API.
# For the weekly sync use: docker compose run --rm api wiki-genres sync
CMD ["uvicorn", "wiki_genres.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
