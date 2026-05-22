"""FastAPI application entrypoint.

M0 ships just the health endpoints + a stub `/v1/stats` so the service shape is
visible. Real read endpoints land in M2 (see docs/PLAN.md § 7).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from wiki_genres import __version__
from wiki_genres.db import dispose_engine, session_scope


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ANN201
    yield
    await dispose_engine()


app = FastAPI(
    title="wiki-genres",
    version=__version__,
    description="Continuously-synced mirror of Wikipedia's music-genre graph.",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness. Returns 200 unconditionally as long as the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness. Verifies the database is reachable."""
    async with session_scope() as session:
        await session.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/v1/stats")
async def stats() -> dict[str, Any]:
    """Surface-level counters. Returns zeros until the bootstrap pipeline lands."""
    async with session_scope() as session:
        # These tables don't exist until migrations run; tolerate that during M0.
        try:
            genres = await session.scalar(text("select count(*) from wg_genres"))
            edges = await session.scalar(text("select count(*) from wg_edges"))
            aliases = await session.scalar(text("select count(*) from wg_aliases"))
        except Exception:  # noqa: BLE001
            genres = edges = aliases = None
    return {
        "version": __version__,
        "genres": genres,
        "edges": edges,
        "aliases": aliases,
    }
