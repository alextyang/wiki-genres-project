"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits.storage import MemoryStorage
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from wiki_genres import __version__
from wiki_genres.api.models import StatsResult
from wiki_genres.api.routes.diff import router as diff_router
from wiki_genres.api.routes.genres import router as genres_router
from wiki_genres.api.routes.resolve import router as resolve_router
from wiki_genres.db import dispose_engine, session_scope

limiter = Limiter(key_func=lambda request: request.client.host, storage_uri="memory://")


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ANN201
    yield
    await dispose_engine()


app = FastAPI(
    title="wiki-genres",
    version=__version__,
    description=(
        "Continuously-synced mirror of Wikipedia's music-genre graph. "
        "Source: https://github.com/alextyang/wiki-genres-project"
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(genres_router)
app.include_router(resolve_router)
app.include_router(diff_router)


# ------------------------------------------------------------------ #
# Health                                                              #
# ------------------------------------------------------------------ #

@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness. Returns 200 unconditionally as long as the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> dict[str, Any]:
    """Readiness. Verifies the database is reachable."""
    try:
        async with session_scope() as session:
            await session.execute(text("select 1"))
        return {"status": "ok", "database": "ok"}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": str(exc)},
        )


# ------------------------------------------------------------------ #
# Stats                                                               #
# ------------------------------------------------------------------ #

@app.get("/v1/stats", response_model=StatsResult)
@limiter.limit("60/minute")
async def stats(request: Request) -> StatsResult:  # noqa: ARG001
    """Node/edge counts, last snapshot, last EventStreams cursor."""
    try:
        async with session_scope() as session:
            genres = await session.scalar(text("SELECT count(*) FROM wg_genres"))
            genres_infobox = await session.scalar(
                text("SELECT count(*) FROM wg_genres WHERE has_infobox")
            )
            edges = await session.scalar(text("SELECT count(*) FROM wg_edges"))
            edges_resolved = await session.scalar(
                text("SELECT count(*) FROM wg_edges WHERE to_genre_id IS NOT NULL")
            )
            aliases = await session.scalar(text("SELECT count(*) FROM wg_aliases"))
            frontier = await session.scalar(text("SELECT count(*) FROM wg_frontier"))

            snap = (await session.execute(
                text("""
                    SELECT id, finished_at
                    FROM wg_snapshots
                    ORDER BY started_at DESC LIMIT 1
                """)
            )).fetchone()

            sync_started = await session.scalar(
                text("SELECT value->>'ts' FROM wg_sync_state WHERE key = 'last_sync_started_at'")
            )
            sync_finished = await session.scalar(
                text("SELECT value->>'ts' FROM wg_sync_state WHERE key = 'last_sync_finished_at'")
            )

        return StatsResult(
            version=__version__,
            genres=genres,
            genres_with_infobox=genres_infobox,
            edges=edges,
            edges_resolved=edges_resolved,
            aliases=aliases,
            last_snapshot_id=snap[0] if snap else None,
            last_snapshot_finished=snap[1] if snap else None,
            last_sync_started_at=sync_started,
            last_sync_finished_at=sync_finished,
            frontier_depth=frontier,
        )
    except Exception:  # noqa: BLE001
        # Tables may not exist if migrations haven't run yet.
        return StatsResult(
            version=__version__,
            genres=None,
            genres_with_infobox=None,
            edges=None,
            edges_resolved=None,
            aliases=None,
            last_snapshot_id=None,
            last_snapshot_finished=None,
            last_sync_started_at=None,
            last_sync_finished_at=None,
            frontier_depth=None,
        )
