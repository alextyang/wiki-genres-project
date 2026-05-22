"""wiki-genres operator CLI."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer

from wiki_genres import __version__
from wiki_genres.logging_config import configure_logging

app = typer.Typer(
    name="wiki-genres",
    help="Operator interface for the wiki-genres service.",
    no_args_is_help=True,
)


def _run(coro):  # noqa: ANN001, ANN201
    """Run a coroutine in the event loop, handling KeyboardInterrupt cleanly."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        raise typer.Exit(code=130)


@app.command()
def version() -> None:
    """Print the installed version and exit."""
    typer.echo(__version__)


@app.command()
def bootstrap(
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n", help="Stop after this many genres (for testing)."
    ),
    single: Optional[str] = typer.Option(
        None, "--single", help="Crawl exactly one Wikipedia title and exit."
    ),
    from_cache: bool = typer.Option(
        False, "--from-cache", help="Use disk-cached fetches only; never hit the network."
    ),
    skip_wikidata: bool = typer.Option(
        False, "--skip-wikidata", help="Skip Wikidata entity fetches (faster, less data)."
    ),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Concurrent requests."),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Run the full bootstrap crawl: seed → fetch → parse → load → resolve edges.

    The bootstrap is fully restartable: already-processed genres are skipped.
    Use --single for a quick one-page test run before a full crawl.

    Example:
        wiki-genres bootstrap --single "Electro (music)"
        wiki-genres bootstrap --limit 100
        wiki-genres bootstrap
    """
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.crawler.bootstrap import run_bootstrap

    stats = _run(
        run_bootstrap(
            limit=limit,
            single_title=single,
            from_cache=from_cache,
            skip_wikidata=skip_wikidata,
            concurrency=concurrency,
        )
    )
    typer.echo(
        f"Done. genres={stats.genres_processed} failed={stats.genres_failed} "
        f"edges_resolved={stats.edges_resolved} "
        f"elapsed={stats.elapsed_seconds:.1f}s"
    )
    if stats.genres_failed:
        raise typer.Exit(code=1)


@app.command()
def sync(
    staleness_days: int = typer.Option(
        7, "--staleness-days", help="Refetch genres older than N days."
    ),
    skip_wikidata: bool = typer.Option(
        False, "--skip-wikidata", help="Skip Wikidata entity fetches (faster)."
    ),
    concurrency: int = typer.Option(4, "--concurrency", "-c"),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Run the weekly sync: SPARQL diff + stale refetch + edge resolve + snapshot.

    Designed to be called from a system cron job:

        0 6 * * 0  docker compose run --rm api wiki-genres sync

    The sync is idempotent — if it crashes mid-run, restarting it resumes via
    the durable frontier table.
    """
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.crawler.sync import run_sync

    stats = _run(
        run_sync(
            staleness_days=staleness_days,
            skip_wikidata=skip_wikidata,
            concurrency=concurrency,
        )
    )
    typer.echo(
        f"Done. new={stats.new_genres_discovered} stale_enqueued={stats.stale_genres_enqueued} "
        f"processed={stats.genres_processed} failed={stats.genres_failed} "
        f"edges_resolved={stats.edges_resolved} elapsed={stats.elapsed_seconds:.1f}s"
    )
    if stats.genres_failed:
        raise typer.Exit(code=1)


@app.command()
def resolve(
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run only the edge-resolution pass (pass 2). Useful after a partial bootstrap."""
    configure_logging(level=log_level)
    from wiki_genres.loader.loader import resolve_edges

    resolved = _run(resolve_edges())
    typer.echo(f"Resolved {resolved} edges.")


@app.command()
def migrate(
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Apply pending database migrations."""
    configure_logging(level=log_level)
    from wiki_genres.db_migrations import apply_migrations

    applied = _run(apply_migrations())
    if applied:
        typer.echo(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        typer.echo("No pending migrations.")


@app.command()
def stats(
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Print genre/edge counts and the last snapshot summary."""
    configure_logging(level=log_level)

    async def _stats() -> None:
        from sqlalchemy import text
        from wiki_genres.db import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            genres = await conn.scalar(text("select count(*) from wg_genres"))
            edges = await conn.scalar(text("select count(*) from wg_edges"))
            unresolved = await conn.scalar(
                text("select count(*) from wg_edges where to_genre_id is null")
            )
            aliases = await conn.scalar(text("select count(*) from wg_aliases"))
            row = await conn.execute(
                text(
                    "select id, finished_at, nodes_total, edges_total, notes "
                    "from wg_snapshots order by started_at desc limit 1"
                )
            )
            last_snap = row.fetchone()

        typer.echo(f"genres:          {genres}")
        typer.echo(f"edges:           {edges}")
        typer.echo(f"  unresolved:    {unresolved}")
        typer.echo(f"aliases:         {aliases}")
        if last_snap:
            typer.echo(f"last snapshot:   {last_snap.id}")
            typer.echo(f"  finished:      {last_snap.finished_at}")
            typer.echo(f"  nodes/edges:   {last_snap.nodes_total}/{last_snap.edges_total}")

    _run(_stats())


@app.command()
def refetch(
    title: str = typer.Argument(help="Wikipedia page title to re-crawl."),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Re-crawl a single Wikipedia title and update the database."""
    configure_logging(level=log_level)
    from wiki_genres.crawler.bootstrap import run_bootstrap

    stats_obj = _run(run_bootstrap(single_title=title))
    typer.echo(
        f"Done. genres={stats_obj.genres_processed} failed={stats_obj.genres_failed}"
    )


if __name__ == "__main__":
    app()
