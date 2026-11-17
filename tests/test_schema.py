import sqlite3

import pytest

from deferred_imports.mining import schema

TABLES = {
    "run_info", "commits", "files", "file_paths", "file_changes", "raw_imports", "file_edges",
    "modules", "file_modules", "module_edges", "module_touches", "problems", "splits",
}


def tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def add_commit(con, i):
    con.execute("INSERT INTO commits (i, sha, date, author_hash, n_parents, n_files, is_fix, "
                "is_revert, is_agent) VALUES (?, ?, '2026-01-01T00:00:00+00:00', 'h', 1, 1, "
                "0, 0, 0)", (i, f"{i:040x}"))


def test_new_database_has_every_table(tmp_path):
    con = schema.connect(tmp_path / "r.sqlite")
    assert tables(con) == TABLES
    assert con.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reopen_keeps_the_data(tmp_path):
    con = schema.connect(tmp_path / "r.sqlite")
    add_commit(con, 0)
    con.commit()
    con.close()
    con = schema.connect(tmp_path / "r.sqlite")
    assert con.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 1


def test_old_schema_version_is_refused(tmp_path):
    path = tmp_path / "r.sqlite"
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA user_version = {schema.SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(RuntimeError, match="mine the repository again"):
        schema.connect(path)


def test_foreign_keys_are_enforced(tmp_path):
    con = schema.connect(tmp_path / "r.sqlite")
    with pytest.raises(sqlite3.IntegrityError):  # commit 5 does not exist
        con.execute("INSERT INTO files (file_id, first_i) VALUES (1, 5)")


def test_checks_reject_bad_rows(tmp_path):
    con = schema.connect(tmp_path / "r.sqlite")
    add_commit(con, 0)
    con.execute("INSERT INTO modules (module_id, name, from_i) VALUES (1, 'db', 0), "
                "(2, 'orders', 0)")
    for bad in ["(0, 1, 2, 0, 'top_level', 'import')",    # delta 0
                "(0, 1, 1, 1, 'top_level', 'import')",    # edge inside one module
                "(0, 1, 2, 1, 'top_level', 'repair')"]:   # unknown cause
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(f"INSERT INTO module_edges VALUES {bad}")


def test_worked_example_crossing_then_repair(tmp_path):
    """docs/schema.md: db -> orders is crossed at commit 501 and repaired at 508."""
    con = schema.connect(tmp_path / "r.sqlite")
    for i in (0, 501, 508):
        add_commit(con, i)
    con.execute("INSERT INTO modules (module_id, name, from_i) VALUES (1, 'shop.db', 0), "
                "(2, 'shop.orders', 0)")
    con.execute("INSERT INTO module_edges VALUES (501, 1, 2, 1, 'top_level', 'import'), "
                "(508, 1, 2, -1, 'top_level', 'import')")
    weight = ("SELECT COALESCE(SUM(delta), 0) FROM module_edges "
              "WHERE src_mod = 1 AND dst_mod = 2 AND i <= ?")
    assert [con.execute(weight, (i,)).fetchone()[0] for i in (500, 501, 507, 508)] == [0, 1, 1, 0]
