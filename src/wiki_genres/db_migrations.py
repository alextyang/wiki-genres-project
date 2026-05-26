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
        await conn.execute(
            text("""
            create table if not exists _migrations (
                name        text primary key,
                applied_at  timestamptz not null default now()
            )
        """)
        )

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
    return _split_sql_statements(sql)


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL on statement semicolons while preserving quoted bodies."""
    statements: list[str] = []
    start = 0
    i = 0
    quote: str | None = None
    dollar_quote: str | None = None

    while i < len(sql):
        char = sql[i]

        if dollar_quote is not None:
            if sql.startswith(dollar_quote, i):
                i += len(dollar_quote)
                dollar_quote = None
                continue
            i += 1
            continue

        if quote is not None:
            if char == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if char in {"'", '"'}:
            quote = char
            i += 1
            continue

        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if match:
                dollar_quote = match.group(0)
                i += len(dollar_quote)
                continue

        if char == ";":
            statement = sql[start:i].strip()
            if statement:
                statements.append(statement)
            start = i + 1

        i += 1

    statement = sql[start:].strip()
    if statement:
        statements.append(statement)
    return statements


def _strip_sql_comments(sql: str) -> str:
    # Remove single-line comments.
    sql = re.sub(r"--[^\n]*", "", sql)
    # Remove block comments.
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
