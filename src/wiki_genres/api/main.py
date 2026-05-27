"""FastAPI application entrypoint."""

from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from wiki_genres import __version__
from wiki_genres.api.models import StatsResult
from wiki_genres.api.routes.admin import router as admin_router
from wiki_genres.api.routes.diff import router as diff_router
from wiki_genres.api.routes.feedback import router as feedback_router
from wiki_genres.api.routes.genres import router as genres_router
from wiki_genres.api.routes.render import router as render_router
from wiki_genres.api.routes.resolve import router as resolve_router
from wiki_genres.api.routes.timeline import router as timeline_router
from wiki_genres.db import dispose_engine, session_scope

limiter = Limiter(
    key_func=lambda request: request.client.host,
    default_limits=["60/minute"],
    storage_uri="memory://",
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Any:
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
app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))
app.add_middleware(SlowAPIMiddleware)

app.include_router(genres_router)
app.include_router(resolve_router)
app.include_router(diff_router)
app.include_router(feedback_router)
app.include_router(admin_router)
app.include_router(timeline_router)
app.include_router(render_router)


def _load_local_dev_extensions() -> None:
    extensions_dir = Path.cwd() / ".tmp" / "local-dev"
    if not extensions_dir.exists():
        return
    for path in sorted(extensions_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"wiki_genres_local_dev_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if callable(register):
            register(app=app, limiter=limiter, root=extensions_dir)


_load_local_dev_extensions()

# Static explorer UI — mounted AFTER API routers so it never shadows /v1/* or /healthz
_static_dir = Path(__file__).parent / "static"
app.mount("/explorer", StaticFiles(directory=str(_static_dir), html=True), name="explorer")


@app.get("/", include_in_schema=False)
@limiter.exempt
async def root() -> RedirectResponse:
    """Send website visitors to the explorer UI."""
    return RedirectResponse(url="/explorer/")


# ------------------------------------------------------------------ #
# Health                                                              #
# ------------------------------------------------------------------ #


@app.get("/healthz", include_in_schema=False)
@limiter.exempt
async def healthz() -> dict[str, str]:
    """Liveness. Returns 200 unconditionally as long as the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/readyz", include_in_schema=False, response_model=None)
@limiter.exempt
async def readyz() -> dict[str, Any] | Response:
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
async def stats() -> StatsResult:
    """Node/edge counts, last snapshot, last EventStreams cursor."""
    try:
        async with session_scope() as session:
            genres = await session.scalar(
                text("""
                    SELECT count(*) FROM wg_genres
                    WHERE deleted_at IS NULL
                      AND is_non_genre = false
                """)
            )
            genres_infobox = await session.scalar(
                text("""
                    SELECT count(*) FROM wg_genres
                    WHERE has_infobox
                      AND deleted_at IS NULL
                      AND is_non_genre = false
                """)
            )
            edges = await session.scalar(
                text("""
                SELECT count(*)
                FROM wg_edges e
                JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                LEFT JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                WHERE from_g.deleted_at IS NULL
                  AND from_g.is_non_genre = false
                  AND e.is_ignored = false
                  AND (
                    e.to_genre_id IS NULL
                    OR (to_g.deleted_at IS NULL AND to_g.is_non_genre = false)
                  )
            """)
            )
            edges_resolved = await session.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_edges e
                    JOIN wg_genres from_g ON from_g.id = e.from_genre_id
                    JOIN wg_genres to_g ON to_g.id = e.to_genre_id
                    WHERE from_g.deleted_at IS NULL
                      AND from_g.is_non_genre = false
                      AND e.is_ignored = false
                      AND to_g.deleted_at IS NULL
                      AND to_g.is_non_genre = false
                """)
            )
            aliases = await session.scalar(
                text("""
                    SELECT count(*)
                    FROM wg_aliases a
                    JOIN wg_genres g ON g.id = a.genre_id
                    WHERE g.deleted_at IS NULL
                      AND g.is_non_genre = false
                """)
            )
            frontier = await session.scalar(text("SELECT count(*) FROM wg_frontier"))

            snap = (
                await session.execute(
                    text("""
                    SELECT id, finished_at
                    FROM wg_snapshots
                    ORDER BY started_at DESC LIMIT 1
                """)
                )
            ).fetchone()

            sync_started = await session.scalar(
                text("SELECT value#>>'{}'  FROM wg_sync_state WHERE key = 'last_sync_started_at'")
            )
            sync_finished = await session.scalar(
                text("SELECT value#>>'{}' FROM wg_sync_state WHERE key = 'last_sync_finished_at'")
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
