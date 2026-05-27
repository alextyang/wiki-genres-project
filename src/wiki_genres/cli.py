"""wiki-genres operator CLI."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

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
        raise typer.Exit(code=130) from None


@app.command()
def version() -> None:
    """Print the installed version and exit."""
    typer.echo(__version__)


@app.command()
def bootstrap(
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Stop after this many genres (for testing)."
    ),
    single: str | None = typer.Option(
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
def index_inbound_relationships(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute inferred edges and print counts without writing to the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of inferred edges to print for review.",
    ),
    max_path_depth: int = typer.Option(
        8,
        "--max-path-depth",
        min=2,
        help="Maximum existing graph depth used to suppress ancestor shortcuts.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Build conservative inferred parent -> child edges from inbound evidence.

    Graph-visible inferred edges stay high-confidence. Broader inbound coverage
    is indexed as `related_genre`; reverse coverage keeps inverse evidence
    labels like `subgenre_of` without becoming display traversal edges.
    """
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.inbound_indexer import index_inbound_relationships as run_indexer

    stats = _run(
        run_indexer(
            dry_run=dry_run,
            sample_size=sample,
            max_path_depth=max_path_depth,
        )
    )

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"inbound index ({mode})")
    typer.echo(f"  candidates:              {stats.candidates}")
    typer.echo(f"  inferred/inserted:       {stats.inserted}")
    typer.echo(f"    display edges:         {stats.display_inserted}")
    typer.echo(f"    related edges:         {stats.related_inserted}")
    typer.echo(f"  deleted existing:        {stats.deleted_existing}")
    typer.echo(f"  skipped self-loop:       {stats.skipped_self_loop}")
    typer.echo(f"  skipped excluded parent: {stats.skipped_excluded_parent}")
    typer.echo(f"  skipped existing direct: {stats.skipped_existing_direct}")
    typer.echo(f"  skipped existing related:{stats.skipped_existing_related}")
    typer.echo(f"  skipped ancestor path:   {stats.skipped_ancestor_shortcut}")
    typer.echo(f"  skipped duplicate cand.: {stats.skipped_duplicate_candidate}")
    typer.echo(f"  skipped promoted region: {stats.skipped_promoted_region_node}")

    if stats.sample:
        typer.echo("sample:")
        for edge in stats.sample:
            typer.echo(
                f"  {edge.parent_title} -> {edge.child_title} ({edge.relation}, {edge.source})"
            )


@app.command("guard-genre-direction")
def guard_genre_direction(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Find weak wrong-direction display edges without updating the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of ignored direction samples to print.",
    ),
    reset_existing: bool = typer.Option(
        True,
        "--reset-existing/--keep-existing",
        help="Clear previous direction-guard flags before recomputing.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Ignore weak display edges that point from a specific genre to a broader base genre."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.genre_direction_guard import guard_genre_direction as run_guard

    stats = _run(
        run_guard(
            dry_run=dry_run,
            sample_size=sample,
            reset_existing=reset_existing,
        )
    )

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"genre direction guard ({mode})")
    typer.echo(f"  display edges scanned:        {stats.edges_scanned}")
    typer.echo(f"  skipped promoted region nodes:{stats.skipped_promoted_region_node}")
    typer.echo(f"  cleared existing:             {stats.cleared_existing}")
    typer.echo(f"  flagged ignored:              {stats.ignored}")
    if stats.sample:
        typer.echo("sample direction flags:")
        for edge in stats.sample:
            typer.echo(
                f"  ignored {edge.from_title} -> {edge.to_title} "
                f"({edge.relation}, {edge.source}; views {edge.from_views}->{edge.to_views})"
            )


@app.command()
def evaluate_year_hints(
    limit: int = typer.Option(
        4000,
        "--limit",
        "-n",
        min=1,
        help="Number of visible genre rows to sample, ordered by pageviews.",
    ),
    samples_per_source: int = typer.Option(
        8,
        "--samples-per-source",
        min=0,
        help="Number of best-hint examples to print per source type.",
    ),
    mismatch_samples: int = typer.Option(
        12,
        "--mismatch-samples",
        min=0,
        help="Number of examples where the new best hint differs from existing origin year.",
    ),
    no_hint_samples: int = typer.Option(
        8,
        "--no-hint-samples",
        min=0,
        help="Number of sampled genres with no timeline hint to print.",
    ),
) -> None:
    """Evaluate candidate timeline year-hint methods without writing to the DB."""
    from wiki_genres.loader.timeline_year_hints import evaluate_year_hint_methods

    evaluation = _run(evaluate_year_hint_methods(limit=limit))
    coverage = (
        evaluation.genres_with_any_hint / evaluation.genres_sampled
        if evaluation.genres_sampled
        else 0
    )

    typer.echo("timeline year hint evaluation")
    typer.echo(f"  genres sampled:       {evaluation.genres_sampled}")
    typer.echo(
        f"  genres with any hint: {evaluation.genres_with_any_hint} ({coverage:.1%})"
    )
    typer.echo(f"  total hints:          {evaluation.total_hints}")
    typer.echo("  best source counts:")
    for source, count in evaluation.best_by_source.most_common():
        typer.echo(f"    {source}: {count}")
    typer.echo("  best confidence counts:")
    for confidence, count in evaluation.best_by_confidence.most_common():
        typer.echo(f"    {confidence}: {count}")

    if samples_per_source:
        typer.echo("samples by source:")
        for source, hints in sorted(evaluation.samples_by_source.items()):
            typer.echo(f"  {source}:")
            for hint in hints[:samples_per_source]:
                end = f"-{hint.year_end}" if hint.year_end else ""
                typer.echo(
                    f"    {hint.title}: {hint.year_start}{end} "
                    f"({hint.confidence}, {hint.year_kind})"
                )
                typer.echo(f"      {hint.evidence}")

    if mismatch_samples:
        typer.echo("mismatch samples vs existing wg_origins parsed year:")
        for sample in evaluation.mismatch_samples[:mismatch_samples]:
            end = f"-{sample['best_year_end']}" if sample["best_year_end"] else ""
            typer.echo(
                f"  {sample['title']}: existing={sample['existing_year_start']} "
                f"best={sample['best_year_start']}{end} "
                f"({sample['source_type']}, {sample['confidence']})"
            )
            typer.echo(f"    {sample['evidence']}")

    if no_hint_samples:
        typer.echo("no-hint samples:")
        for sample in evaluation.no_hint_samples[:no_hint_samples]:
            typer.echo(f"  {sample['title']}: {sample['summary']}")


@app.command()
def index_timeline_year_hints(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute timeline year hints without writing the persisted table.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of materialized best hints to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Rebuild the persisted timeline year-hint table for all visible genres."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.timeline_year_hints import rebuild_timeline_year_hints

    stats = _run(rebuild_timeline_year_hints(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"timeline year hint index ({mode})")
    typer.echo(f"  total genres: {stats.total_genres}")
    typer.echo(f"  hints found:  {stats.hints_found}")
    typer.echo(f"  no hint:      {stats.no_hint}")
    typer.echo(f"  regional out: {stats.excluded_regional}")
    typer.echo(f"  rows written: {stats.rows_written}")
    typer.echo("  by source:")
    for source, count in stats.by_source.most_common():
        typer.echo(f"    {source}: {count}")
    typer.echo("  by confidence:")
    for confidence, count in stats.by_confidence.most_common():
        typer.echo(f"    {confidence}: {count}")
    if stats.sample:
        typer.echo("sample:")
        for hint in stats.sample:
            end = f"-{hint.year_end}" if hint.year_end else ""
            beginning_window = (
                f" beginning={hint.beginning_start}-{hint.beginning_end}"
                if hint.beginning_start is not None and hint.beginning_end is not None
                else ""
            )
            relevance_window = (
                f" relevance={hint.relevance_start}-{hint.relevance_end}"
                if hint.relevance_start is not None and hint.relevance_end is not None
                else f" relevance={hint.relevance_start}-open"
                if hint.relevance_start is not None
                else ""
            )
            typer.echo(
                f"  {hint.title}: {hint.year_start}{end} "
                f"({hint.confidence}, {hint.source_type}"
                f"{beginning_window}{relevance_window})"
            )
            typer.echo(f"    {hint.evidence}")


@app.command()
def flag_circular_relationships(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Find cycle-closing display edges without updating the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of ignored cycle samples to print.",
    ),
    reset_existing: bool = typer.Option(
        True,
        "--reset-existing/--keep-existing",
        help="Clear previous cycle-guard flags before recomputing.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Mark child relationships that would create cycles from the Music root."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.cycle_guard import flag_circular_relationships as run_cycle_guard

    stats = _run(
        run_cycle_guard(
            dry_run=dry_run,
            sample_size=sample,
            reset_existing=reset_existing,
        )
    )

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"cycle guard ({mode})")
    seed_roots_found = stats.roots_found - stats.music_country_roots_found
    typer.echo(f"  seed roots found:  {seed_roots_found}/{stats.roots_requested}")
    if stats.roots_missing:
        typer.echo(f"  roots missing:     {', '.join(stats.roots_missing)}")
    typer.echo(f"  hidden/supplemental roots: {stats.music_country_roots_found}")
    typer.echo(f"  total roots found: {stats.roots_found}")
    typer.echo(f"  relationships:     {stats.edges_scanned}")
    typer.echo(f"  nodes visited:     {stats.nodes_visited}")
    typer.echo(f"  cleared existing:  {stats.cleared_existing}")
    typer.echo(f"  flagged ignored:   {stats.ignored}")

    if stats.sample:
        typer.echo("sample cycles:")
        for cycle in stats.sample:
            typer.echo(
                f"  ignored {cycle.edge.from_title} -> {cycle.edge.to_title} "
                f"({cycle.edge.key.relation}, {cycle.edge.key.source}); "
                f"path: {' -> '.join(cycle.path_titles)}"
            )


@app.command()
def index_music_reachability(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute Music-root reachability without writing to the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of reachable parent rows to print.",
    ),
    max_depth: int = typer.Option(
        16,
        "--max-depth",
        min=1,
        help="Maximum display-edge depth to index from the synthetic Music root.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Index all display parents that are reachable from the Music root."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.music_reachability import index_music_reachability as run_indexer

    stats = _run(
        run_indexer(
            dry_run=dry_run,
            sample_size=sample,
            max_depth=max_depth,
        )
    )

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"music reachability ({mode})")
    seed_roots_found = stats.roots_found - stats.music_country_roots_found
    typer.echo(f"  seed roots found:     {seed_roots_found}/{stats.roots_requested}")
    if stats.roots_missing:
        typer.echo(f"  roots missing:        {', '.join(stats.roots_missing)}")
    typer.echo(f"  hidden/supplemental roots: {stats.music_country_roots_found}")
    typer.echo(f"  total roots found:    {stats.roots_found}")
    typer.echo(f"  active genres:        {stats.total_genres}")
    typer.echo(f"  display edges:        {stats.edges_scanned}")
    typer.echo(f"  reachable nodes:      {stats.reachable_nodes}")
    typer.echo(f"  orphaned nodes:       {stats.orphaned_nodes}")
    typer.echo(f"  indexed parent edges: {stats.indexed_parent_edges}")
    typer.echo(f"  cleared existing:     {stats.deleted_existing}")
    typer.echo(f"  skipped cycles:       {stats.skipped_cycle_edges}")
    typer.echo(f"  skipped max depth:    {stats.skipped_depth_limited_edges}")

    if stats.sample:
        typer.echo("sample reachable parents:")
        for row in stats.sample:
            typer.echo(
                f"  {row.parent_title} -> {row.title} "
                f"({row.parent_relation}, parent depth {row.parent_depth_from_music}, "
                f"child depth {row.depth_from_music}); "
                f"path: {' -> '.join(('Music', *row.path_titles))}"
            )

    if stats.orphan_sample:
        typer.echo("sample orphaned genres:")
        for genre in stats.orphan_sample:
            views = genre.monthly_views_p30 if genre.monthly_views_p30 is not None else "unknown"
            typer.echo(f"  {genre.title} ({genre.genre_id}, views30={views})")


@app.command("index-genre-colors")
def index_genre_colors(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute similarity colors without writing to the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of color rows to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Index root-affinity colors for graph-similarity coloring."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.genre_colors import index_genre_colors as run_indexer

    stats = _run(run_indexer(dry_run=dry_run, sample_size=sample))

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"genre colors ({mode})")
    typer.echo(f"  roots found:     {stats.roots_found}/{stats.roots_requested}")
    if stats.roots_missing:
        typer.echo(f"  roots missing:   {', '.join(stats.roots_missing)}")
    typer.echo(f"  active genres:   {stats.total_genres}")
    typer.echo(f"  display edges:   {stats.edges_scanned}")
    typer.echo(f"  colored genres:  {stats.colored_genres}")
    typer.echo(f"  cleared existing:{stats.deleted_existing}")

    if stats.sample:
        typer.echo("sample colors:")
        for row in stats.sample:
            affinity = ", ".join(
                f"{root} {value:.2f}" for root, value in list(row.root_affinity.items())[:3]
            )
            typer.echo(
                f"  {row.title}: {row.color_hex} (confidence {row.confidence:.2f}; {affinity})"
            )


@app.command("index-semantic-cloud-layout")
def index_semantic_cloud_layout(
    root_genre_id: str | None = typer.Option(
        None,
        "--root-genre-id",
        help=(
            "Optional genre id to build a scoped cloud centered on that genre. "
            "Omit for the general Music cloud."
        ),
    ),
    region_id: str | None = typer.Option(
        None,
        "--region-id",
        help="Optional country/region id to build a region-scoped cloud.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute vectors, edges, and coordinates without writing tables.",
    ),
    sample: int = typer.Option(
        20,
        "--sample",
        min=0,
        help="Number of high-priority positioned genres to print.",
    ),
    iterations: int = typer.Option(
        90,
        "--iterations",
        min=0,
        help="Deterministic force-layout iterations.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Build the purpose-made semantic placement index for cloud mode."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.semantic_cloud_layout import build_semantic_cloud_layout

    stats = _run(
        build_semantic_cloud_layout(
            root_genre_id=root_genre_id,
            region_id=region_id,
            dry_run=dry_run,
            sample_size=sample,
            iterations=iterations,
        )
    )
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"semantic cloud layout ({mode})")
    typer.echo(f"  layout key:        {stats.layout_key}")
    typer.echo(f"  genres:            {stats.total_genres}")
    typer.echo(f"  vector rows:       {stats.vector_rows}")
    typer.echo(f"  semantic edges:    {stats.semantic_edges}")
    typer.echo(f"  graph edges:       {stats.graph_edges}")
    typer.echo(f"  materialized edges:{stats.materialized_edges}")
    typer.echo(f"  layout rows:       {stats.layout_rows}")
    typer.echo(f"  cleared vectors:   {stats.deleted_vectors}")
    typer.echo(f"  cleared edges:     {stats.deleted_edges}")
    typer.echo(f"  cleared layouts:   {stats.deleted_layouts}")
    if stats.quality_metrics:
        typer.echo("  quality:")
        for key, value in stats.quality_metrics.items():
            typer.echo(f"    {key}: {value}")
    if stats.sample:
        typer.echo("sample positions:")
        for row in stats.sample:
            terms = ", ".join(row["terms"])
            typer.echo(
                f"  {row['title']}: ({row['x']}, {row['y']}) "
                f"root={row['root']} terms={terms}"
            )


@app.command("compact-semantic-cloud-radial")
def compact_semantic_cloud_radial(
    root_genre_id: str | None = typer.Option(
        None,
        "--root-genre-id",
        help="Optional scoped cloud layout id. Omit for the general Music cloud.",
    ),
    region_id: str | None = typer.Option(
        None,
        "--region-id",
        help="Optional country/region cloud layout id.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute compacted coordinates without writing radial_x/radial_y.",
    ),
    sample: int = typer.Option(
        12,
        "--sample",
        min=0,
        help="Number of inward-compacted sample rows to print.",
    ),
    lanes: int = typer.Option(
        96,
        "--lanes",
        min=16,
        help="Angular constraint lanes around the Music center.",
    ),
    radius_step: float = typer.Option(
        8.0,
        "--radius-step",
        min=2.0,
        help="Radius search step in layout units.",
    ),
    angular_steps: int = typer.Option(
        8,
        "--angular-steps",
        min=1,
        help="Number of angular offsets to search on each side of the original ray.",
    ),
    inner_radius: float = typer.Option(
        0.0,
        "--inner-radius",
        min=0.0,
        help="Minimum radius to start center-out placement search.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Pack an existing semantic cloud layout inward into radial_x/radial_y."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.radial_cloud_compaction import (
        compact_semantic_cloud_layout_radially,
    )

    stats = _run(
        compact_semantic_cloud_layout_radially(
            root_genre_id=root_genre_id,
            region_id=region_id,
            dry_run=dry_run,
            sample_size=sample,
            lanes=lanes,
            radius_step=radius_step,
            angular_steps=angular_steps,
            inner_radius=inner_radius,
        )
    )
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"radial cloud compaction ({mode})")
    typer.echo(f"  layout key:    {stats.layout_key}")
    typer.echo(f"  nodes:         {stats.total_nodes}")
    typer.echo(f"  updated nodes: {stats.updated_nodes}")
    if stats.metrics:
        typer.echo("  metrics:")
        for key, value in stats.metrics.items():
            typer.echo(f"    {key}: {value}")
    if stats.sample:
        typer.echo("sample radial positions:")
        for row in stats.sample:
            typer.echo(
                f"  {row['title']}: ({row['x']}, {row['y']}) -> "
                f"({row['radial_x']}, {row['radial_y']}) ratio={row['radius_ratio']}"
            )


@app.command("cache-wikipedia-page-content")
def cache_wikipedia_page_content(
    from_cache: bool = typer.Option(
        False,
        "--from-cache",
        help="Only use the local HTTP cache; do not fetch missing pages.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum active genre pages to inspect/cache.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Store active genre-page wikitext in the local DB content cache."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.db import get_engine
    from sqlalchemy import text
    from wiki_genres.loader.country_affinity import ensure_wikipedia_page_content_cache

    async def _cache_pages():
        engine = get_engine()
        async with engine.connect() as conn:
            titles = list(
                (
                    await conn.execute(
                        text("""
                            SELECT wikipedia_title
                            FROM wg_genres
                            WHERE deleted_at IS NULL
                              AND is_non_genre = false
                            ORDER BY wikipedia_title
                            LIMIT coalesce(:limit_value, 2147483647)
                        """),
                        {"limit_value": limit},
                    )
                )
                .scalars()
                .all()
            )
        stats = await ensure_wikipedia_page_content_cache(
            titles=titles,
            from_cache=from_cache,
        )
        return titles, stats

    titles, stats = _run(_cache_pages())
    typer.echo("wikipedia page content cache")
    typer.echo(f"  titles:         {len(titles)}")
    typer.echo(f"  already cached: {stats.content_cached}")
    typer.echo(f"  fetched:        {stats.content_fetched}")
    typer.echo(f"  failed:         {stats.content_failed}")


@app.command("index-country-affinities")
def index_country_affinities_command(
    dry_run: bool = typer.Option(False, "--dry-run"),
    fetch_missing_content: bool = typer.Option(
        False,
        "--fetch-missing-content",
        help="Fetch/store missing active genre wikitext before scoring content mentions.",
    ),
    from_cache: bool = typer.Option(
        False,
        "--from-cache",
        help="When fetching missing content, only use the local HTTP cache.",
    ),
    limit: int | None = typer.Option(None, "--limit", min=1),
    min_score: float = typer.Option(0.55, "--min-score", min=0.0, max=1.0),
    min_confidence: float = typer.Option(0.5, "--min-confidence", min=0.0, max=1.0),
    sample: int = typer.Option(25, "--sample", min=0),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Interpret all genres against country regions and write affinity rows."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.country_affinity import index_country_affinities

    stats = _run(
        index_country_affinities(
            dry_run=dry_run,
            fetch_missing_content=fetch_missing_content,
            from_cache=from_cache,
            limit=limit,
            min_score=min_score,
            min_confidence=min_confidence,
            sample_size=sample,
        )
    )
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"country affinities ({mode})")
    typer.echo(f"  genres:           {stats.genres_seen}")
    typer.echo(f"  countries:        {stats.countries_seen}")
    typer.echo(f"  affinities:       {stats.affinities_written}")
    typer.echo(f"  deleted existing: {stats.deleted_existing}")
    typer.echo(f"  cached pages:     {stats.content_cached}")
    typer.echo(f"  fetched pages:    {stats.content_fetched}")
    typer.echo(f"  failed pages:     {stats.content_failed}")
    if stats.source_distribution:
        typer.echo("  sources:")
        for key, value in sorted(stats.source_distribution.items()):
            typer.echo(f"    {key}: {value}")
    if stats.sample:
        typer.echo("sample affinities:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("country-affinity-report")
def country_affinity_report_command(
    region_id: str | None = typer.Option(None, "--region-id"),
    limit: int = typer.Option(25, "--limit", min=1),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Summarize country-affinity coverage by country."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.country_affinity import country_affinity_report

    rows = _run(country_affinity_report(region_id=region_id, limit=limit))
    typer.echo("country affinity report")
    for row in rows:
        typer.echo(
            f"  {row['canonical_name']} ({row['region_id']}): "
            f"{row['affinities']} affinities, {row['needs_review']} needs review"
        )
        if row.get("sources"):
            typer.echo(f"    sources: {row['sources']}")


@app.command("curate-genres")
def curate_genres(
    force_non_genre_title: list[str] | None = typer.Option(
        None,
        "--force-non-genre-title",
        help=(
            "Wikipedia title to force back to non-genre after temporary source-page "
            "discovery. Repeat the option for multiple titles."
        ),
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Reapply the strict public-genre approval filter to all database rows."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.curation import apply_genre_curation

    stats = _run(
        apply_genre_curation(
            force_non_genre_titles=force_non_genre_title or [],
        )
    )
    typer.echo("genre curation filter")
    typer.echo(f"  total rows:       {stats.total_rows}")
    typer.echo(f"  approved rows:    {stats.approved_rows}")
    typer.echo(f"  non-genre rows:   {stats.non_genre_rows}")
    typer.echo(f"  changed rows:     {stats.changed_rows}")
    typer.echo(f"  forced non-genre: {stats.forced_non_genre_rows}")
    typer.echo(f"  manual edges:     {stats.manual_edges_upserted}")
    if stats.manual_edges_missing_titles:
        typer.echo(f"  missing manual titles: {', '.join(stats.manual_edges_missing_titles)}")


@app.command("seed-region-graph")
def seed_region_graph(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Inspect approved Music of ... pages without writing region graph rows.",
    ),
    sample: int = typer.Option(
        10,
        "--sample",
        min=0,
        help="Number of seeded region pages to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Seed the region graph substrate from approved regional music pages."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_graph import seed_music_region_pages

    stats = _run(seed_music_region_pages(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region graph seed ({mode})")
    typer.echo(f"  music pages found:    {stats.music_pages_found}")
    typer.echo(f"  regions upserted:     {stats.regions_upserted}")
    typer.echo(f"  sources upserted:     {stats.sources_upserted}")
    typer.echo(f"  music pages upserted: {stats.music_pages_upserted}")
    if stats.skipped_titles:
        typer.echo(f"  skipped titles:       {', '.join(stats.skipped_titles)}")
    if stats.sample:
        typer.echo("sample region pages:")
        for page in stats.sample:
            typer.echo(f"  {page.region_id}: {page.wikipedia_title} -> {page.region_name}")


@app.command("seed-region-discovery-sources")
def seed_region_discovery_sources(
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Seed Phase 2 regional category/list discovery sources."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import seed_region_discovery_sources as run_seed

    count = _run(run_seed())
    typer.echo(f"region discovery sources seeded: {count}")


@app.command("discover-region-candidates")
def discover_region_candidates(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Fetch and parse sources without writing candidates.",
    ),
    from_cache: bool = typer.Option(
        False,
        "--from-cache",
        help="Use only cached Wikimedia responses.",
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Clear existing Phase 2 discovery sources/candidates before running.",
    ),
    max_category_depth: int = typer.Option(
        2,
        "--max-category-depth",
        min=0,
        help="Maximum category recursion depth to process.",
    ),
    max_sources: int | None = typer.Option(
        None,
        "--max-sources",
        min=1,
        help="Maximum pending sources to process in this run.",
    ),
    max_category_pages: int = typer.Option(
        3,
        "--max-category-pages",
        min=1,
        help="Maximum categorymembers API pages to fetch per category source.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of discovered candidates to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Discover regional music candidate pages from categories and list pages."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import (
        discover_region_candidates as run_discovery,
    )
    from wiki_genres.loader.region_discovery import (
        reset_region_discovery,
    )

    async def _run_command():
        if reset:
            await reset_region_discovery()
        return await run_discovery(
            dry_run=dry_run,
            from_cache=from_cache,
            max_category_depth=max_category_depth,
            max_sources=max_sources,
            max_category_pages=max_category_pages,
            sample_size=sample,
        )

    stats = _run(_run_command())
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region candidate discovery ({mode})")
    typer.echo(f"  sources seeded:       {stats.sources_seeded}")
    typer.echo(f"  sources processed:    {stats.sources_processed}")
    typer.echo(f"  sources failed:       {stats.sources_failed}")
    typer.echo(f"  category members:     {stats.category_members_seen}")
    typer.echo(f"  list links:           {stats.list_links_seen}")
    typer.echo(f"  candidates found:     {stats.candidates_found}")
    typer.echo(f"  candidates upserted:  {stats.candidates_upserted}")
    typer.echo(f"  sources discovered:   {stats.discovered_sources_upserted}")
    if stats.errors:
        typer.echo("errors:")
        for error in stats.errors[:10]:
            typer.echo(f"  {error}")
    if stats.sample:
        typer.echo("sample candidates:")
        for candidate in stats.sample:
            section = f" [{candidate.source_section}]" if candidate.source_section else ""
            typer.echo(
                f"  {candidate.candidate_type}: {candidate.title}{section} "
                f"({candidate.status}, {candidate.confidence:.2f})"
            )


@app.command("export-region-review-batch")
def export_region_review_batch(
    output: Path = typer.Argument(help="Output JSONL path for GPT review workers."),
    limit: int = typer.Option(200, "--limit", min=1, help="Maximum rows to export."),
    candidate_type: str | None = typer.Option(
        None,
        "--candidate-type",
        help="Optional candidate_type filter.",
    ),
    source_type: str | None = typer.Option(
        None,
        "--source-type",
        help="Optional source_type filter.",
    ),
    min_confidence: float | None = typer.Option(
        None,
        "--min-confidence",
        min=0,
        max=1,
        help="Optional inclusive lower confidence bound.",
    ),
    max_confidence: float | None = typer.Option(
        None,
        "--max-confidence",
        min=0,
        max=1,
        help="Optional inclusive upper confidence bound.",
    ),
    status: str = typer.Option(
        "needs_gpt_review",
        "--status",
        help="Candidate status to export.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Export Phase 2 regional candidates as GPT-worker JSONL."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import export_region_review_batch as run_export

    stats = _run(
        run_export(
            output,
            limit=limit,
            candidate_type=candidate_type,
            source_type=source_type,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            status=status,
        )
    )
    typer.echo(f"region review batch exported: {stats.rows_exported}")
    typer.echo(f"  output: {stats.output_path}")


@app.command("import-region-review-batch")
def import_region_review_batch(
    input_path: Path = typer.Argument(help="Input JSONL path from GPT review workers."),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Import GPT-worker JSONL decisions into Phase 2 candidate staging rows."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import import_region_review_batch as run_import

    stats = _run(run_import(input_path))
    typer.echo("region review batch imported")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  rows updated:  {stats.rows_updated}")
    typer.echo(f"  rows rejected: {stats.rows_rejected}")
    if stats.errors:
        typer.echo("errors:")
        for error in stats.errors[:20]:
            typer.echo(f"  {error}")
        if len(stats.errors) > 20:
            typer.echo(f"  ... {len(stats.errors) - 20} more")


@app.command("auto-review-region-candidates")
def auto_review_region_candidates(
    include_existing_reviewed: bool = typer.Option(
        False,
        "--include-existing-reviewed",
        help="Re-apply deterministic review even to rows that already have gpt_review payloads.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Conservatively triage remaining Phase 2 candidates."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import auto_review_region_candidates as run_review

    stats = _run(run_review(include_existing_reviewed=include_existing_reviewed))
    typer.echo("region candidate auto-review complete")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  rows updated:  {stats.rows_updated}")
    typer.echo(f"  accepted:      {stats.accepted}")
    typer.echo(f"  rejected:      {stats.rejected}")
    typer.echo(f"  needs review:  {stats.needs_review}")


@app.command("finalize-region-candidate-reviews")
def finalize_region_candidate_reviews(
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Resolve all remaining Phase 2 review rows before Phase 3 staging."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_discovery import finalize_region_candidate_reviews as run_review

    stats = _run(run_review())
    typer.echo("region candidate manual review complete")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  rows updated:  {stats.rows_updated}")
    typer.echo(f"  accepted:      {stats.accepted}")
    typer.echo(f"  rejected:      {stats.rejected}")


@app.command("build-region-relationship-proposals")
def build_region_relationship_proposals(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Clear Phase 3 region relationship staging tables before rebuilding.",
    ),
    sample: int = typer.Option(
        10,
        "--sample",
        min=0,
        help="Number of proposed relationship samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Build Phase 3 region hierarchy and region-to-genre staging edges."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_graph import build_region_relationship_proposals as run_build

    stats = _run(run_build(reset=reset, sample_size=sample))
    typer.echo("region relationship proposals built")
    typer.echo(f"  candidates seen:            {stats.candidates_seen}")
    typer.echo(f"  regions upserted:           {stats.regions_upserted}")
    typer.echo(f"  sources upserted:           {stats.sources_upserted}")
    typer.echo(f"  region relationships:       {stats.region_relationships_upserted}")
    typer.echo(f"  region-genre relationships: {stats.region_genre_relationships_upserted}")
    typer.echo(f"  music page links:           {stats.music_pages_upserted}")
    typer.echo(f"  skipped candidates:         {stats.skipped_candidates}")
    if stats.sample:
        typer.echo("sample proposals:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("rebuild-pure-region-graph")
def rebuild_pure_region_graph(
    sample: int = typer.Option(
        10,
        "--sample",
        min=0,
        help="Number of derived mapping/relationship samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Rebuild derived pure region node mappings and region relationships."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.pure_region_graph import rebuild_pure_region_graph as run_rebuild

    stats = _run(run_rebuild(sample_size=sample))
    typer.echo("pure region graph rebuilt")
    typer.echo(f"  node mappings:   {stats.mappings_upserted}")
    typer.echo(f"  regions touched: {stats.regions_upserted}")
    typer.echo(f"  relationships:   {stats.relationships_upserted}")
    typer.echo(f"  skipped titles:  {stats.skipped_title_mappings}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("extract-region-page-genres")
def extract_region_page_genres(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Fetch and parse regional pages without writing proposals.",
    ),
    reset_existing: bool = typer.Option(
        False,
        "--reset-existing",
        help="Clear previous article-link proposals from this extractor before writing.",
    ),
    only_new: bool = typer.Option(
        False,
        "--only-new",
        help="Insert only relationships/sources that do not already exist; never update conflicts.",
    ),
    from_cache: bool = typer.Option(
        False,
        "--from-cache",
        help="Only use cached Wikipedia responses.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Limit pages for a small verification run.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of extracted links/failures to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Stage exact genre links found directly on regional music pages."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_page_extraction import (
        extract_region_page_genres as run_extract,
    )

    stats = _run(
        run_extract(
            dry_run=dry_run,
            reset_existing=reset_existing,
            only_new=only_new,
            from_cache=from_cache,
            limit=limit,
            sample_size=sample,
        )
    )

    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region page genre extraction ({mode})")
    typer.echo(f"  pages seen:         {stats.pages_seen}")
    typer.echo(f"  pages fetched:      {stats.pages_fetched}")
    typer.echo(f"  pages failed:       {stats.pages_failed}")
    typer.echo(f"  pages with links:   {stats.pages_with_links}")
    typer.echo(f"  links seen:         {stats.links_seen}")
    typer.echo(f"  proposals upserted: {stats.proposals_upserted}")
    typer.echo(f"  sources upserted:   {stats.sources_upserted}")
    typer.echo(f"  deleted proposals:  {stats.deleted_existing_relationships}")
    typer.echo(f"  deleted sources:    {stats.deleted_existing_sources}")

    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")

    if stats.failed_sample:
        typer.echo("failed sample:")
        for item in stats.failed_sample:
            typer.echo(f"  {item}")


@app.command("audit-region-page-genre-coverage")
def audit_region_page_genre_coverage(
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of regions without direct child genres to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Audit direct region-to-genre coverage after regional page extraction."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_page_extraction import (
        audit_region_page_genre_coverage as run_audit,
    )

    stats = _run(run_audit(sample_size=sample))
    typer.echo("region page genre coverage audit")
    typer.echo(f"  promoted regions:              {stats.promoted_regions}")
    typer.echo(f"  regions with direct genres:    {stats.regions_with_direct_genres}")
    typer.echo(f"  regions without direct genres: {stats.regions_without_direct_genres}")
    typer.echo(f"  regions with article genres:   {stats.regions_with_article_genres}")
    typer.echo(f"  accepted region-genre edges:   {stats.accepted_edges}")
    typer.echo(f"  article-derived edges:         {stats.article_edges}")
    typer.echo(f"  pending region-genre edges:    {stats.pending_edges}")
    typer.echo(f"  rejected region-genre edges:   {stats.rejected_edges}")
    if stats.sample_without_direct_genres:
        typer.echo("sample without direct genres:")
        for item in stats.sample_without_direct_genres:
            typer.echo(f"  {item}")


@app.command("classify-region-genre-ownership")
def classify_region_genre_ownership(
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of classification samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Split regional page links into graph ownership vs local style mentions."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_ownership import (
        classify_existing_region_genre_ownership as run_classify,
    )

    stats = _run(run_classify(sample_size=sample))
    typer.echo("region genre ownership classification complete")
    typer.echo(f"  rows seen:                {stats.rows_seen}")
    typer.echo(f"  rows updated:             {stats.rows_updated}")
    typer.echo(f"  owned regional genres:    {stats.owned_regional_genre}")
    typer.echo(f"  regional style mentions:  {stats.regional_style_mention}")
    typer.echo(f"  influence/context rows:   {stats.influence_or_context}")
    typer.echo(f"  bad matches:              {stats.bad_match}")
    if stats.sample:
        typer.echo("sample classifications:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("classify-region-genre-ownership-v2")
def classify_region_genre_ownership_v2(
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of classification samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Run evidence-first v2 classifier and stage inferred regional variants."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_ownership_v2 import (
        classify_existing_region_genre_ownership_v2 as run_classify,
    )

    stats = _run(run_classify(sample_size=sample))
    typer.echo("region genre ownership v2 classification complete")
    typer.echo(f"  rows seen:               {stats.rows_seen}")
    typer.echo(f"  rows updated:            {stats.rows_updated}")
    typer.echo(f"  owned regional genres:   {stats.owned_regional_genre}")
    typer.echo(f"  style mentions:          {stats.regional_style_mention}")
    typer.echo(f"  inferred candidates:     {stats.inferred_candidate}")
    typer.echo(f"  rejected:               {stats.rejected}")
    typer.echo(f"  needs review:            {stats.needs_review}")
    if stats.sample:
        typer.echo("sample classifications:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("audit-region-variant-coverage")
def audit_region_variant_coverage(
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of inferred candidates to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Summarize inferred regional variant candidate coverage."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_ownership_v2 import audit_region_variant_coverage as run_audit

    report = _run(run_audit(sample_size=sample))
    typer.echo("region inferred variant coverage")
    counts = report.get("counts") or {}
    for key in sorted(counts.keys()):
        typer.echo(f"  {key}: {counts[key]}")
    sample_rows = report.get("sample") or []
    if sample_rows:
        typer.echo("sample:")
        for row in sample_rows:
            typer.echo(
                f"  {row.get('candidate_kind')}: {row.get('region_name')} -> {row.get('proposed_display_title')}"
            )


@app.command("review-region-relationship-proposals")
def review_region_relationship_proposals(
    sample: int = typer.Option(
        10,
        "--sample",
        min=0,
        help="Number of reviewed relationship samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Run Phase 4 source-specific review over staged regional relationships."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_validation import (
        review_region_relationship_proposals as run_review,
    )

    stats = _run(run_review(sample_size=sample))
    typer.echo("region relationship proposal review complete")
    typer.echo(f"  region rows seen:          {stats.region_rows_seen}")
    typer.echo(f"  region rows updated:       {stats.region_rows_updated}")
    typer.echo(f"  region accepted:           {stats.region_accepted}")
    typer.echo(f"  region rejected:           {stats.region_rejected}")
    typer.echo(f"  region needs review:       {stats.region_needs_review}")
    typer.echo(f"  region-genre rows seen:    {stats.region_genre_rows_seen}")
    typer.echo(f"  region-genre rows updated: {stats.region_genre_rows_updated}")
    typer.echo(f"  region-genre accepted:     {stats.region_genre_accepted}")
    typer.echo(f"  region-genre rejected:     {stats.region_genre_rejected}")
    typer.echo(f"  region-genre needs review: {stats.region_genre_needs_review}")
    if stats.sample:
        typer.echo("sample reviews:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("audit-region-promotion-readiness")
def audit_region_promotion_readiness(
    sample: int = typer.Option(
        10,
        "--sample",
        min=0,
        help="Number of audit samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Audit accepted regional edges before any live graph/API promotion."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_validation import audit_region_promotion_readiness as run_audit

    stats = _run(run_audit(sample_size=sample))
    typer.echo("region promotion readiness audit")
    typer.echo(f"  promotion ready:              {stats.promotion_ready}")
    typer.echo(f"  accepted region edges:        {stats.accepted_region_relationships}")
    typer.echo(f"  accepted region-genre edges:  {stats.accepted_region_genre_relationships}")
    typer.echo(f"  rejected region edges:        {stats.rejected_region_relationships}")
    typer.echo(f"  rejected region-genre edges:  {stats.rejected_region_genre_relationships}")
    typer.echo(f"  pending region edges:         {stats.pending_region_relationships}")
    typer.echo(f"  pending region-genre edges:   {stats.pending_region_genre_relationships}")
    typer.echo(f"  containment cycles:           {stats.containment_cycles}")
    typer.echo(f"  accepted container edges:     {stats.accepted_container_region_edges}")
    typer.echo(f"  accepted artifact edges:      {stats.accepted_artifact_genre_edges}")
    typer.echo(f"  broad region-genre edges:     {stats.broad_region_genre_edges}")
    typer.echo(f"  duplicate region-genre pairs: {stats.duplicate_region_genre_pairs}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("audit-region-production-readiness")
def audit_region_production_readiness(
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Write JSON and Markdown audit artifacts to this directory.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of sample rows to include per audit bucket.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Audit whether the regional graph is production-ready."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_production import (
        audit_region_production_readiness as run_audit,
    )

    stats = _run(run_audit(output_dir=output_dir, sample_size=sample))
    typer.echo("region production readiness audit")
    typer.echo(f"  production ready:                   {stats.production_ready}")
    typer.echo(f"  regions:                            {stats.regions}")
    typer.echo(f"  promoted regions:                   {stats.promoted_regions}")
    typer.echo(f"  region relationships:               {stats.region_relationships}")
    typer.echo(f"  region-genre relationships:         {stats.region_genre_relationships}")
    typer.echo(
        f"  accepted graph region-genre edges:  {stats.accepted_graph_region_genre_relationships}"
    )
    typer.echo(f"  zero-child promoted regions:        {stats.zero_child_promoted_regions}")
    typer.echo(f"  parentless promoted regions:        {stats.parentless_accepted_regions}")
    typer.echo(f"  alias/style proxy candidates:       {stats.alias_proxy_candidates}")
    typer.echo(f"  invalid promoted region titles:     {stats.invalid_region_titles}")
    typer.echo(f"  duplicate region-genre pairs:       {stats.duplicate_region_genre_pairs}")
    typer.echo(f"  broad region-genre edges:           {stats.broad_region_genre_edges}")
    typer.echo(f"  graph-affecting needs-review rows:  {stats.graph_affecting_needs_review}")
    typer.echo(f"  pending candidate rows:             {stats.pending_candidate_rows}")
    if stats.report_path:
        typer.echo(f"  report:                             {stats.report_path}")
    if stats.json_path:
        typer.echo(f"  json:                               {stats.json_path}")


@app.command("export-region-production-review-batches")
def export_region_production_review_batches(
    output_dir: Path = typer.Argument(
        Path("tmp/region_production_reviews"),
        help="Directory where JSONL review batches should be written.",
    ),
    review_type: str | None = typer.Option(
        None,
        "--review-type",
        help="Export only one review type.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Optional maximum rows per review type.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=1,
        help="Maximum candidate titles requested in each GPT review row.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Export GPT-5.4-mini region production review queues."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_production import (
        export_region_production_review_batches as run_export,
    )

    stats = _run(
        run_export(
            output_dir=output_dir,
            review_type=review_type,
            limit=limit,
            sample_size=sample,
        )
    )
    typer.echo("region production review batches exported")
    typer.echo(f"  output dir: {stats.output_dir}")
    typer.echo(f"  total rows: {stats.total_rows}")
    for exported_type, rows in sorted(stats.rows_by_type.items()):
        typer.echo(f"  {exported_type}: {rows} -> {stats.files_by_type[exported_type]}")


@app.command("import-region-production-review-decisions")
def import_region_production_review_decisions(
    input_path: Path = typer.Argument(..., help="Reviewed JSONL decision file."),
    batch_key: str | None = typer.Option(None, "--batch-key"),
    reviewer_model: str = typer.Option("gpt-5.4-mini", "--reviewer-model"),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Import reviewed production decisions into staging tables."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_production import (
        import_region_production_review_decisions as run_import,
    )

    stats = _run(
        run_import(
            input_path=input_path,
            batch_key=batch_key,
            reviewer_model=reviewer_model,
        )
    )
    typer.echo("region production review decisions imported")
    typer.echo(f"  input:         {stats.input_path}")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  imported:      {stats.rows_imported}")
    typer.echo(f"  needs human:   {stats.rows_needing_human}")
    typer.echo(f"  rejected:      {stats.rows_rejected}")
    if stats.errors:
        typer.echo("errors:")
        for error in stats.errors[:20]:
            typer.echo(f"  {error}")


@app.command("apply-region-production-review-decisions")
def apply_region_production_review_decisions(
    dry_run: bool = typer.Option(False, "--dry-run"),
    sample: int = typer.Option(25, "--sample", min=0),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Apply high-confidence staged production review decisions."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_production import (
        apply_region_production_review_decisions as run_apply,
    )

    stats = _run(run_apply(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region production review decisions applied ({mode})")
    typer.echo(f"  decisions seen:       {stats.decisions_seen}")
    typer.echo(f"  decisions applied:    {stats.decisions_applied}")
    typer.echo(f"  needs human:          {stats.decisions_needing_human}")
    typer.echo(f"  anchors added:        {stats.anchors_added}")
    typer.echo(f"  candidate edges add.: {stats.candidate_edges_added}")
    typer.echo(f"  relationships demoted:{stats.relationships_demoted}")
    typer.echo(f"  regions marked:       {stats.regions_marked}")
    typer.echo(f"  regions renamed:      {stats.regions_renamed}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("apply-region-hierarchy-pass")
def apply_region_hierarchy_pass(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Evaluate the full hierarchy/accessibility pass without writing changes.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of hierarchy/accessibility samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Apply full regional hierarchy/accessibility heuristics to all regions."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_hierarchy import (
        apply_region_hierarchy_accessibility_pass as run_pass,
    )

    stats = _run(run_pass(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region hierarchy/accessibility pass ({mode})")
    typer.echo(f"  regions seen:                  {stats.regions_seen}")
    typer.echo(f"  country kind updates:          {stats.country_kind_updates}")
    typer.echo(f"  territory kind updates:        {stats.territory_kind_updates}")
    typer.echo(f"  special map subregions promoted:{stats.special_map_subregions_promoted}")
    typer.echo(f"  superregions approved:         {stats.superregions_approved}")
    typer.echo(f"  low-value regions collapsed:   {stats.low_value_regions_collapsed}")
    typer.echo(f"  child genre edges copied up:   {stats.low_value_relationships_copied}")
    typer.echo(f"  child region edges reparented: {stats.child_relationships_reparented}")
    typer.echo(f"  redundant parent edges rejected:{stats.redundant_parent_edges_rejected}")
    typer.echo(f"  explicit parent edges added:   {stats.explicit_parent_edges_added}")
    typer.echo(f"  invalid titles fixed:          {stats.invalid_titles_fixed}")
    typer.echo(f"  source regions collapsed:      {stats.source_regions_collapsed}")
    typer.echo(f"  style proxy regions demoted:   {stats.style_proxy_regions_demoted}")
    typer.echo(f"  accessibility rows marked:     {stats.accessibility_rows_marked}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("canonicalize-region-alias-proxies")
def canonicalize_region_alias_proxies(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print deterministic proxy merges without modifying the DB.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of merge samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Merge demonym/style proxy regions into canonical country/territory regions."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_production import (
        canonicalize_region_alias_proxies as run_cleanup,
    )

    stats = _run(run_cleanup(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region alias proxy canonicalization ({mode})")
    typer.echo(f"  candidates seen:       {stats.candidates_seen}")
    typer.echo(f"  candidates merged:     {stats.candidates_merged}")
    typer.echo(f"  child genre edges add.:{stats.genre_edges_added}")
    typer.echo(f"  sources copied:        {stats.sources_copied}")
    typer.echo(f"  music pages copied:    {stats.music_pages_copied}")
    typer.echo(f"  region edges copied:   {stats.region_edges_copied}")
    typer.echo(f"  region-genre copied:   {stats.region_genre_edges_copied}")
    typer.echo(f"  candidates repointed:  {stats.candidates_repointed}")
    typer.echo(f"  old regions deleted:   {stats.old_regions_deleted}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("apply-region-post-review-cleanup")
def apply_region_post_review_cleanup(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Evaluate deterministic remaining-region review fixes without writing.",
    ),
    sample: int = typer.Option(
        25,
        "--sample",
        min=0,
        help="Number of cleanup samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Apply deterministic fixes from the full-region subworker review."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_post_review_cleanup import (
        apply_region_post_review_cleanup as run_cleanup,
    )

    stats = _run(run_cleanup(dry_run=dry_run, sample_size=sample))
    mode = "dry-run" if dry_run else "write"
    typer.echo(f"region post-review cleanup ({mode})")
    typer.echo(f"  region status updates:          {stats.region_status_updates}")
    typer.echo(f"  region kind updates:            {stats.region_kind_updates}")
    typer.echo(f"  region title updates:           {stats.region_title_updates}")
    typer.echo(f"  parent edges rejected:          {stats.parent_edges_rejected}")
    typer.echo(f"  region-genre edges rejected:    {stats.region_genre_edges_rejected}")
    typer.echo(f"  city genre edges accepted:      {stats.city_genre_edges_accepted}")
    typer.echo(f"  collapsed display edges rejected:{stats.collapsed_display_edges_rejected}")
    typer.echo(f"  stale city visibility updates:  {stats.stale_city_visibility_updates}")
    typer.echo(f"  hierarchy edges added:          {stats.hierarchy_edges_added}")
    typer.echo(f"  duplicate region edges rejected:{stats.duplicate_region_edges_rejected}")
    typer.echo(
        f"  duplicate region-genre rejected:{stats.duplicate_region_genre_edges_rejected}"
    )
    typer.echo(f"  inferred variant edges added:   {stats.inferred_variant_edges_added}")
    typer.echo(f"  inferred variants resolved:     {stats.inferred_variants_resolved}")
    typer.echo(
        "  fuzzy base equivalents resolved:"
        f"{stats.fuzzy_base_equivalent_variants_resolved}"
    )
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("index-genre-merge-candidates")
def index_genre_merge_candidates(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Clear existing staged merge candidates before indexing.",
    ),
    limit: int = typer.Option(
        5000,
        "--limit",
        min=1,
        help="Maximum merge candidates to stage.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of candidate samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Stage likely duplicate genre nodes for merge review."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.merge_review import index_genre_merge_candidates as run_index

    stats = _run(run_index(reset=reset, limit=limit, sample_size=sample))
    typer.echo("genre merge candidate similarity pass")
    typer.echo(f"  rows seen:        {stats.rows_seen}")
    typer.echo(f"  rows upserted:    {stats.rows_upserted}")
    typer.echo(f"  deleted existing: {stats.deleted_existing}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("export-tree-review-batches")
def export_tree_review_batches(
    output_dir: Path = typer.Argument(help="Directory for tree review JSON batches."),
    limit_roots: int = typer.Option(
        8,
        "--limit-roots",
        min=1,
        help="Number of largest Music-root sections to export.",
    ),
    max_nodes: int = typer.Option(
        350,
        "--max-nodes",
        min=25,
        help="Maximum nodes per exported root section.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of exported batch samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Export top-level tree sections for GPT review workers."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.merge_review import export_tree_review_batches as run_export

    stats = _run(
        run_export(
            output_dir,
            limit_roots=limit_roots,
            max_nodes_per_batch=max_nodes,
            sample_size=sample,
        )
    )
    typer.echo("tree review batches exported")
    typer.echo(f"  batches exported: {stats.batches_exported}")
    typer.echo(f"  nodes exported:   {stats.nodes_exported}")
    typer.echo(f"  edges exported:   {stats.edges_exported}")
    typer.echo(f"  output dir:       {stats.output_dir}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("import-tree-review-findings")
def import_tree_review_findings(
    input_path: Path = typer.Argument(help="GPT tree review JSONL file."),
    batch_key: str | None = typer.Option(
        None,
        "--batch-key",
        help="Optional batch key when findings do not include one.",
    ),
    reviewer_model: str = typer.Option(
        "gpt-5.4-mini",
        "--reviewer-model",
        help="Reviewer model label to record.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Import GPT tree review JSONL findings into staging."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.merge_review import import_tree_review_findings as run_import

    stats = _run(
        run_import(
            input_path,
            batch_key=batch_key,
            reviewer_model=reviewer_model,
        )
    )
    typer.echo("tree review findings imported")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  rows imported: {stats.rows_imported}")
    typer.echo(f"  rows rejected: {stats.rows_rejected}")
    if stats.errors:
        typer.echo("errors:")
        for error in stats.errors[:20]:
            typer.echo(f"  {error}")
        if len(stats.errors) > 20:
            typer.echo(f"  ... {len(stats.errors) - 20} more")


@app.command("index-region-merge-candidates")
def index_region_merge_candidates(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Clear existing staged region merge candidates before indexing.",
    ),
    limit: int = typer.Option(
        5000,
        "--limit",
        min=1,
        help="Maximum region merge candidates to stage.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of candidate samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Stage likely duplicate region nodes for regional graph review."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_review import index_region_merge_candidates as run_index

    stats = _run(run_index(reset=reset, limit=limit, sample_size=sample))
    typer.echo("region merge candidate similarity pass")
    typer.echo(f"  rows seen:        {stats.rows_seen}")
    typer.echo(f"  rows upserted:    {stats.rows_upserted}")
    typer.echo(f"  deleted existing: {stats.deleted_existing}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("export-region-tree-review-batches")
def export_region_tree_review_batches(
    output_dir: Path = typer.Argument(help="Directory for regional tree review JSON batches."),
    limit_roots: int = typer.Option(
        24,
        "--limit-roots",
        min=1,
        help="Number of largest regional root sections to export.",
    ),
    max_regions: int = typer.Option(
        300,
        "--max-regions",
        min=25,
        help="Maximum regions per exported root section.",
    ),
    sample: int = typer.Option(
        15,
        "--sample",
        min=0,
        help="Number of exported batch samples to print.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Export regional hierarchy sections for GPT review workers."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_review import export_region_tree_review_batches as run_export

    stats = _run(
        run_export(
            output_dir,
            limit_roots=limit_roots,
            max_regions_per_batch=max_regions,
            sample_size=sample,
        )
    )
    typer.echo("region tree review batches exported")
    typer.echo(f"  batches exported:    {stats.batches_exported}")
    typer.echo(f"  regions exported:    {stats.regions_exported}")
    typer.echo(f"  region edges:        {stats.region_edges_exported}")
    typer.echo(f"  region-genre edges:  {stats.genre_edges_exported}")
    typer.echo(f"  output dir:          {stats.output_dir}")
    if stats.sample:
        typer.echo("sample:")
        for item in stats.sample:
            typer.echo(f"  {item}")


@app.command("import-region-tree-review-findings")
def import_region_tree_review_findings(
    input_path: Path = typer.Argument(help="GPT regional tree review JSONL file."),
    batch_key: str | None = typer.Option(
        None,
        "--batch-key",
        help="Optional batch key when findings do not include one.",
    ),
    reviewer_model: str = typer.Option(
        "gpt-5.4-mini",
        "--reviewer-model",
        help="Reviewer model label to record.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Import GPT regional tree review JSONL findings into staging."""
    configure_logging(level=log_level, fmt=log_format)
    from wiki_genres.loader.region_review import import_region_tree_review_findings as run_import

    stats = _run(
        run_import(
            input_path,
            batch_key=batch_key,
            reviewer_model=reviewer_model,
        )
    )
    typer.echo("region tree review findings imported")
    typer.echo(f"  rows seen:     {stats.rows_seen}")
    typer.echo(f"  rows imported: {stats.rows_imported}")
    typer.echo(f"  rows rejected: {stats.rows_rejected}")
    if stats.errors:
        typer.echo("errors:")
        for error in stats.errors[:20]:
            typer.echo(f"  {error}")
        if len(stats.errors) > 20:
            typer.echo(f"  ... {len(stats.errors) - 20} more")


@app.command("playlist-add")
def playlist_add(
    genre_id: str = typer.Argument(help="Genre id, such as wg-q188450."),
    song_title: str = typer.Option(..., "--title", help="Song title."),
    artist: str = typer.Option(..., "--artist", help="Artist name."),
    youtube_url: str = typer.Option(..., "--youtube-url", help="YouTube watch/embed/share URL."),
    ordinal: int | None = typer.Option(
        None,
        "--ordinal",
        min=0,
        help="Playlist position. Defaults to appending after the current last track.",
    ),
    playlist_discovery_group: str = typer.Option(
        "manual",
        "--playlist-discovery-group",
        "--discovery-version",
        help="Playlist discovery group label for later enrichment passes.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Add or replace one manual YouTube playlist track for a genre."""
    configure_logging(level=log_level)
    from wiki_genres.loader.genre_playlists import add_playlist_track

    try:
        track = _run(
            add_playlist_track(
                genre_id=genre_id,
                song_title=song_title,
                artist=artist,
                youtube_url=youtube_url,
                ordinal=ordinal,
                playlist_discovery_group=playlist_discovery_group,
            )
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"saved {track.genre_id} #{track.ordinal}: "
        f"{track.artist} - {track.song_title} ({track.youtube_url})"
    )


@app.command("playlist-import")
def playlist_import(
    csv_path: Path = typer.Argument(
        help="CSV with genre_id,song_title,artist,youtube_url,ordinal."
    ),
    replace_genres: bool = typer.Option(
        False,
        "--replace-genres",
        help="Delete existing playlist rows for genres present in the CSV before import.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Import manual YouTube playlist rows from a local CSV file."""
    configure_logging(level=log_level)
    from wiki_genres.loader.genre_playlists import import_playlist_csv

    try:
        stats = _run(import_playlist_csv(csv_path, replace_genres=replace_genres))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("playlist import complete")
    typer.echo(f"  rows read:      {stats.rows_read}")
    typer.echo(f"  rows written:   {stats.rows_written}")
    typer.echo(f"  genres touched: {stats.genres_touched}")


@app.command("playlist-list")
def playlist_list(
    genre_id: str = typer.Argument(help="Genre id, such as wg-q188450."),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Print the manual YouTube playlist for a genre."""
    configure_logging(level=log_level)
    from wiki_genres.loader.genre_playlists import list_playlist_tracks

    tracks = _run(list_playlist_tracks(genre_id))
    if not tracks:
        typer.echo("No playlist tracks.")
        return

    for track in tracks:
        typer.echo(
            f"{track.ordinal}. {track.artist} - {track.song_title} "
            f"({track.youtube_url}) [{track.playlist_discovery_group}]"
        )


@app.command("playlist-preflight")
def playlist_preflight(
    genre_id: str | None = typer.Option(
        None,
        "--genre-id",
        help="Optional genre id to restrict checks (e.g. wg-q188450).",
    ),
    concurrency: int = typer.Option(
        64,
        "--concurrency",
        "-c",
        min=1,
        help="Concurrent YouTube preflight requests.",
    ),
    ttl_days: int = typer.Option(
        30,
        "--ttl-days",
        min=1,
        help="Reuse cached results newer than this many days.",
    ),
    limit_urls: int | None = typer.Option(
        None,
        "--limit-urls",
        min=1,
        help="Optional limit on unique URLs checked.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-check even when cached / already checked.",
    ),
    target_count: int = typer.Option(
        35,
        "--target-count",
        min=1,
        help="Desired usable playlist rows per genre for the shortfall report.",
    ),
    shortfall_csv: Path | None = typer.Option(
        None,
        "--shortfall-csv",
        help="Optional CSV path for genres needing a second translation pass.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Preflight playlist URLs for iframe embeddability (high concurrency)."""
    configure_logging(level=log_level)
    from wiki_genres.loader.youtube_embed_preflight import (
        playlist_embed_shortfalls,
        preflight_youtube_embeds,
    )

    async def _run_preflight_and_shortfalls():
        stats = await preflight_youtube_embeds(
            genre_id=genre_id,
            concurrency=concurrency,
            ttl_days=ttl_days,
            limit_urls=limit_urls,
            force=force,
        )
        shortfalls = await playlist_embed_shortfalls(target_count=target_count)
        return stats, shortfalls

    stats, shortfalls = _run(
        _run_preflight_and_shortfalls()
    )
    typer.echo("playlist preflight complete")
    typer.echo(f"  urls seen:        {stats.urls_seen}")
    typer.echo(f"  urls checked:     {stats.urls_checked}")
    typer.echo(f"  urls cached:      {stats.urls_cached}")
    typer.echo(f"  urls embeddable:  {stats.urls_embeddable}")
    typer.echo(f"  urls blocked:     {stats.urls_unembeddable}")
    typer.echo(f"  target count:     {target_count}")
    typer.echo(f"  shortfall genres: {len(shortfalls)}")
    if shortfall_csv is not None:
        shortfall_csv.parent.mkdir(parents=True, exist_ok=True)
        with shortfall_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "genre_id",
                    "title",
                    "usable_count",
                    "blocked_count",
                    "checked_count",
                    "needed_count",
                ],
            )
            writer.writeheader()
            for row in shortfalls:
                writer.writerow(
                    {
                        "genre_id": row.genre_id,
                        "title": row.title,
                        "usable_count": row.usable_count,
                        "blocked_count": row.blocked_count,
                        "checked_count": row.checked_count,
                        "needed_count": row.needed_count,
                    }
                )
        typer.echo(f"  shortfall csv:    {shortfall_csv}")


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


@app.command("import-reviewed-genre-relationships")
def import_reviewed_genre_relationships(
    csv_path: Path = typer.Argument(
        help="Normalized GPT relationship-review CSV to import.",
    ),
    review_run_id: str = typer.Option(
        "relationship_review_20260527",
        "--review-run-id",
        help="Stable identifier for this reviewed relationship run.",
    ),
    replace: bool = typer.Option(
        True,
        "--replace/--append",
        help="Delete existing rows for this review run before importing.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Import reviewed genre relationships into the canonical new schema."""
    configure_logging(level=log_level)
    from wiki_genres.loader.genre_relationship_import import (
        import_reviewed_genre_relationships as run_import,
    )

    stats = _run(
        run_import(
            csv_path,
            review_run_id=review_run_id,
            replace_review_run=replace,
        )
    )
    typer.echo(f"rows read:                 {stats.rows_read}")
    typer.echo(f"relationships inserted:   {stats.relationships_inserted}")
    typer.echo(f"missing targets inserted: {stats.missing_targets_inserted}")
    typer.echo(f"self relationships skipped:{stats.skipped_self_relationships}")
    typer.echo(f"missing sources skipped:  {stats.skipped_missing_source_genres}")
    typer.echo(f"old relationships deleted:{stats.deleted_existing_relationships}")
    typer.echo(f"old missing deleted:      {stats.deleted_existing_missing_targets}")


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
            genres = await conn.scalar(
                text("""
                    select count(*) from wg_genres
                    where deleted_at is null
                      and is_non_genre = false
                """)
            )
            edges = await conn.scalar(
                text("""
                select count(*)
                from wg_relationship_detail_edges e
                join wg_genres from_g on from_g.id = e.from_genre_id
                left join wg_genres to_g on to_g.id = e.to_genre_id
                where from_g.is_non_genre = false
                  and from_g.deleted_at is null
                  and e.is_ignored = false
                  and (
                    e.to_genre_id is null
                    or (to_g.is_non_genre = false and to_g.deleted_at is null)
                  )
            """)
            )
            unresolved = await conn.scalar(
                text("""
                    select count(*)
                    from wg_relationship_detail_edges e
                    join wg_genres g on g.id = e.from_genre_id
                    where e.to_genre_id is null
                      and e.is_ignored = false
                      and g.deleted_at is null
                      and g.is_non_genre = false
                """)
            )
            aliases = await conn.scalar(
                text("""
                    select count(*)
                    from wg_aliases a
                    join wg_genres g on g.id = a.genre_id
                    where g.deleted_at is null
                      and g.is_non_genre = false
                """)
            )
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
def fill_pageviews(
    concurrency: int = typer.Option(
        8,
        "--concurrency",
        "-c",
        help="Concurrent Wikimedia requests.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Backfill pageview data for every genre that doesn't have it yet.

    Safe to run against an already-populated DB: only genres with
    monthly_views_p30 IS NULL are processed. Interrupted runs can be
    restarted — they resume from where they left off.

    Example (run once bootstrap is done):
        wiki-genres fill-pageviews --concurrency 12
    """
    configure_logging(level=log_level, fmt=log_format)

    async def _run_fill() -> None:
        import asyncio

        from sqlalchemy import text

        from wiki_genres.crawler.fetcher import WikiFetcher
        from wiki_genres.db import get_engine
        from wiki_genres.db_migrations import apply_migrations
        from wiki_genres.loader.loader import load_pageviews

        await apply_migrations()

        engine = get_engine()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("""
                    SELECT id, wikipedia_title
                    FROM wg_genres
                    WHERE monthly_views_p30 IS NULL
                      AND deleted_at IS NULL
                      AND is_non_genre = false
                    ORDER BY wikipedia_title
                """)
                )
            ).fetchall()

        total = len(rows)
        typer.echo(f"Genres missing pageviews: {total}")
        if not total:
            return

        fetcher = WikiFetcher()
        sem = asyncio.Semaphore(concurrency)
        done = 0
        failed = 0

        async def _one(genre_id: str, title: str) -> None:
            nonlocal done, failed
            async with sem:
                try:
                    result = await fetcher.fetch_pageviews(title)
                    if result.ok:
                        items = result.json().get("items", [])
                        if items:
                            await load_pageviews(genre_id, items)
                    done += 1
                    if done % 100 == 0:
                        typer.echo(f"  {done}/{total} done, {failed} failed")
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    typer.echo(f"  WARN {title}: {exc}", err=True)

        tasks = [asyncio.create_task(_one(r[0], r[1])) for r in rows]
        await asyncio.gather(*tasks, return_exceptions=True)
        await fetcher.aclose()

        typer.echo(f"Done. filled={done} failed={failed} total={total}")

    _run(_run_fill())


@app.command()
def refetch(
    title: str = typer.Argument(help="Wikipedia page title to re-crawl."),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Re-crawl a single Wikipedia title and update the database."""
    configure_logging(level=log_level)
    from wiki_genres.crawler.bootstrap import run_bootstrap

    stats_obj = _run(run_bootstrap(single_title=title))
    typer.echo(f"Done. genres={stats_obj.genres_processed} failed={stats_obj.genres_failed}")


@app.command("crawl-page-links")
def crawl_page_links(
    titles: list[str] = typer.Argument(
        help="Source Wikipedia pages whose internal links should be tested as genres."
    ),
    max_links_per_page: int = typer.Option(
        300,
        "--max-links-per-page",
        min=1,
        help="Maximum source-page links to test after filtering namespaces and sections.",
    ),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Concurrent crawls."),
    skip_wikidata: bool = typer.Option(
        False, "--skip-wikidata", help="Skip Wikidata entity fetches for linked pages."
    ),
    unapprove_empty_sources: bool = typer.Option(
        True,
        "--unapprove-empty-sources/--keep-empty-sources-approved",
        help="Mark source pages non-genre if none of their links resolve to approved genres.",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
    log_format: str = typer.Option("pretty", "--log-format"),
) -> None:
    """Crawl likely genre pages linked from broader source pages.

    This is intended for pages such as "Music of Vanuatu": first load the
    source page itself, then test its article links with the normal strict
    genre classifier. Links that are not music genres are skipped by the same
    filter used by bootstrap.
    """
    configure_logging(level=log_level, fmt=log_format)

    async def _crawl() -> None:
        import asyncio

        import mwparserfromhell
        from sqlalchemy import text

        from wiki_genres.crawler.bootstrap import BootstrapStats
        from wiki_genres.crawler.fetcher import WikiFetcher
        from wiki_genres.db import get_engine
        from wiki_genres.db_migrations import apply_migrations
        from wiki_genres.loader.curation import apply_genre_curation
        from wiki_genres.loader.loader import log_fetch, resolve_edges

        await apply_migrations()
        fetcher = WikiFetcher()
        stats = BootstrapStats()
        sem = asyncio.Semaphore(concurrency)
        links_by_source: dict[str, list[str]] = {}
        empty_sources: list[str] = []
        attempted_links = 0

        try:
            for title in titles:
                source_links = await _source_links(
                    fetcher,
                    title,
                    max_links_per_page=max_links_per_page,
                    mwparserfromhell=mwparserfromhell,
                    log_fetch=log_fetch,
                    normalise_title=_normalise_link_title,
                    skip_link=_skip_link_title,
                )
                links_by_source[title] = source_links
                typer.echo(f"{title}: {len(source_links)} links queued for genre testing")
                await _crawl_one(fetcher, title, skip_wikidata, sem, stats)

            unique_links = sorted({link for links in links_by_source.values() for link in links})
            unique_links = await _filter_uncrawled_titles(unique_links)
            attempted_links = len(unique_links)

            async def _linked(title: str) -> None:
                await _crawl_one(fetcher, title, skip_wikidata, sem, stats)

            await asyncio.gather(*[asyncio.create_task(_linked(title)) for title in unique_links])
            stats.edges_resolved = await resolve_edges()

            if unapprove_empty_sources:
                engine = get_engine()
                async with engine.connect() as conn:
                    for source, links in links_by_source.items():
                        approved_link_count = await conn.scalar(
                            text("""
                                SELECT count(*)
                                FROM wg_genres
                                WHERE wikipedia_title = ANY(:links)
                                  AND deleted_at IS NULL
                                  AND is_non_genre = false
                            """),
                            {"links": links},
                        )
                        if int(approved_link_count or 0) == 0:
                            empty_sources.append(source)

            curation = await apply_genre_curation(
                force_non_genre_titles=empty_sources if unapprove_empty_sources else []
            )
        finally:
            await fetcher.aclose()

        typer.echo("page-link crawl complete")
        typer.echo(f"  source pages:         {len(titles)}")
        typer.echo(f"  linked titles tested: {attempted_links}")
        typer.echo(f"  skipped by filter:    {stats.genres_skipped}")
        typer.echo(f"  failed fetches:       {stats.genres_failed}")
        typer.echo(f"  edges resolved:       {stats.edges_resolved}")
        typer.echo(f"  curation changed:     {curation.changed_rows}")
        if empty_sources:
            typer.echo("  unapproved empty sources:")
            for source in empty_sources:
                typer.echo(f"    {source}")

    async def _crawl_one(
        fetcher,  # noqa: ANN001
        title: str,
        skip_wikidata: bool,
        sem,  # noqa: ANN001
        stats,  # noqa: ANN001
    ) -> None:
        from wiki_genres.crawler.bootstrap import _fetch_parse_load

        async with sem:
            try:
                await _fetch_parse_load(
                    fetcher=fetcher,
                    title=title,
                    skip_wikidata=skip_wikidata,
                    qid_hint=None,
                    stats=stats,
                    triggered_by="page-link-crawl",
                )
            except Exception as exc:  # noqa: BLE001
                stats.genres_failed += 1
                stats.errors.append(f"{title}: {exc}")
                typer.echo(f"  WARN {title}: {exc}", err=True)

    async def _source_links(
        fetcher,  # noqa: ANN001
        title: str,
        *,
        max_links_per_page: int,
        mwparserfromhell,  # noqa: ANN001
        log_fetch,  # noqa: ANN001
        normalise_title,  # noqa: ANN001
        skip_link,  # noqa: ANN001
    ) -> list[str]:
        result = await fetcher.fetch_wikitext(title)
        await log_fetch(
            url=result.url,
            http_status=result.http_status,
            content_sha256=result.content_sha256,
            elapsed_ms=result.elapsed_ms,
            via="page-link-crawl",
        )
        if not result.ok:
            return []

        parse_block = result.json().get("parse", {})
        wikitext = parse_block.get("wikitext", "")
        source_title = parse_block.get("title", title)
        wikicode = mwparserfromhell.parse(wikitext)
        links: list[str] = []
        seen: set[str] = set()
        for link in wikicode.filter_wikilinks(recursive=True):
            target = normalise_title(str(link.title))
            if skip_link(target) or target == source_title or target in seen:
                continue
            seen.add(target)
            links.append(target)
            if len(links) >= max_links_per_page:
                break
        return links

    async def _filter_uncrawled_titles(candidate_titles: list[str]) -> list[str]:
        if not candidate_titles:
            return []
        from sqlalchemy import text

        from wiki_genres.db import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            existing = {
                row[0]
                for row in await conn.execute(
                    text("""
                        SELECT wikipedia_title
                        FROM wg_genres
                        WHERE wikipedia_title = ANY(:titles)
                    """),
                    {"titles": candidate_titles},
                )
            }
        return [title for title in candidate_titles if title not in existing]

    def _normalise_link_title(raw: str) -> str:
        import re

        raw = raw.split("#", 1)[0].strip().replace("_", " ")
        raw = re.sub(r"\s+", " ", raw)
        if raw.startswith(":"):
            raw = raw[1:]
        if not raw:
            return raw
        return raw[0].upper() + raw[1:]

    def _skip_link_title(title: str) -> bool:
        prefixes = (
            "File:",
            "Image:",
            "Media:",
            "Category:",
            "Wikipedia:",
            "WP:",
            "Help:",
            "Template:",
            "Portal:",
            "Special:",
            "Talk:",
            "User:",
            "Draft:",
            "List of ",
        )
        return (
            not title
            or title.startswith(prefixes)
            or title.startswith(
                (
                    "Timeline of ",
                    "Index of ",
                )
            )
        )

    _run(_crawl())


if __name__ == "__main__":
    app()
