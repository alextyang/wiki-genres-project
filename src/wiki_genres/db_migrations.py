"""Simple file-based migration runner.

Applies `.sql` files from `migrations/` in lexicographic order, skipping any
already recorded in the `_migrations` tracking table.
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine

logger = structlog.get_logger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


async def apply_migrations(migrations_dir: Path = _MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Return names of newly-applied files."""
    engine = get_engine()
    applied: list[str] = []

    async with engine.begin() as conn:
        await conn.execute(text("""
            create table if not exists _migrations (
                name        text primary key,
                applied_at  timestamptz not null default now()
            )
        """))

        for sql_path in sorted(migrations_dir.glob("*.sql")):
            name = sql_path.name
            exists = await conn.scalar(
                text("select 1 from _migrations where name = :n"),
                {"n": name},
            )
            if exists:
                continue

            logger.info("applying_migration", name=name)
            _exec_sql_file(conn, sql_path)
            # We can't await inside a regular function; use run_sync workaround.
            # Instead, collect statements and run them directly.
            statements = _parse_statements(sql_path.read_text())
            for stmt in statements:
                await conn.execute(text(stmt))

            await conn.execute(
                text("insert into _migrations (name) values (:n)"),
                {"n": name},
            )
            applied.append(name)
            logger.info("migration_applied", name=name)

    return applied


def _exec_sql_file(conn: object, path: Path) -> None:  # noqa: ARG001
    """No-op placeholder — actual execution done in caller."""


def _parse_statements(sql: str) -> list[str]:
    """Split SQL into individual executable statements.

    Strips `BEGIN;` / `COMMIT;` wrappers — the migration runner provides its
    own transaction boundary.
    """
    # Drop transaction boundaries (the migration runner wraps everything).
    sql = re.sub(r"(?m)^\s*begin\s*;", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"(?m)^\s*commit\s*;", "", sql, flags=re.IGNORECASE)
    # Strip comments BEFORE splitting — comments can contain semicolons.
    sql = _strip_sql_comments(sql)
    # Split on semicolons; drop empty chunks.
    stmts = []
    for chunk in sql.split(";"):
        stripped = chunk.strip()
        if stripped:
            stmts.append(stripped)
    return stmts


def _strip_sql_comments(sql: str) -> str:
    # Remove single-line comments.
    sql = re.sub(r"--[^\n]*", "", sql)
    # Remove block comments.
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql
