"""Tests for raw SQL migration parsing."""

from __future__ import annotations

from wiki_genres.db_migrations import _parse_statements


def test_parse_statements_keeps_dollar_quoted_blocks_intact() -> None:
    sql = """
    begin;

    create table example (id integer);

    do $$
    begin
        if exists (select 1) then
            update example set id = 1;
        end if;
    end $$;

    insert into example values (2);

    commit;
    """

    statements = _parse_statements(sql)

    assert len(statements) == 3
    assert statements[0] == "create table example (id integer)"
    assert statements[1].startswith("do $$")
    assert "update example set id = 1;" in statements[1]
    assert statements[1].endswith("end $$")
    assert statements[2] == "insert into example values (2)"
