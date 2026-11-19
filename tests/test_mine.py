import sqlite3
import subprocess

import pytest

from deferred_imports.mining import check, mine

TABLES = ["commits", "files", "file_paths", "file_changes", "raw_imports", "problems"]


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def new_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "a@x.com")
    git(path, "config", "user.name", "A")
    return path


def make_demo(tmp_path):
    """4 first-parent commits: init, a merge with an agent PR commit, a rename, and a raw
    commit with a Latin-1 author name and a broken UTF-8 message."""
    repo = new_repo(tmp_path / "demo")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.py").write_text("import os\n")
    (repo / "pkg" / "b.py").write_text("from . import a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "checkout", "-qb", "feat")
    (repo / "pkg" / "b.py").write_text("from . import a\nimport sys\n")
    git(repo, "commit", "-qam", "feature", "-m",
        "Co-Authored-By: Claude <noreply@anthropic.com>")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "feat", "-m", "Merge feat")
    git(repo, "mv", "pkg/a.py", "pkg/c.py")
    git(repo, "commit", "-qm", "Fix bug: move a\n\nConflicts:\n\x01\x02\x03 pkg/a.py")
    # As in scrapy and celery. Written as a raw commit object, because `git commit`
    # would re-encode them to valid UTF-8.
    (repo / "pkg" / "c.py").write_text("import os\nimport re\n")
    git(repo, "add", "-A")
    tree = subprocess.run(["git", "-C", str(repo), "write-tree"], check=True,
                          capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    who = b"Libor Nenad\xe1l <l@x.com> 1700000000 +0000"
    raw = (b"tree " + tree.encode() + b"\nparent " + head.encode() + b"\nauthor " + who
           + b"\ncommitter " + who + b"\n\nadd re \xc3\n")
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "commit", "-w", "--stdin"],
                         input=raw, check=True, capture_output=True).stdout.decode().strip()
    git(repo, "update-ref", "refs/heads/main", sha)
    return repo


def run(repo, db, *extra):
    mine.main([str(repo), "--out", str(db), "--salt-file", str(db.parent / ".salt"), *extra])
    return sqlite3.connect(db)


def dump(db):
    con = sqlite3.connect(db)
    return {t: sorted(con.execute(f"SELECT * FROM {t}"), key=repr) for t in TABLES}


def test_extract_imports_kinds():
    src = (b"import os, a.b as x\nfrom typing import TYPE_CHECKING\n"
           b"if TYPE_CHECKING:\n    from p import B\nelse:\n    import json\n"
           b"try:\n    import ujson\nexcept ImportError:\n    pass\n"
           b"def f():\n    from . import q\n"
           b"from a.b\\\n    .c import D\n")
    imps, err = mine.extract_imports(src)
    assert not err
    assert dict(imps) == {
        ("import os", "top_level"): 1, ("import a.b", "top_level"): 1,
        ("from typing import TYPE_CHECKING", "top_level"): 1,
        ("from p import B", "type_checking"): 1, ("import json", "top_level"): 1,
        ("import ujson", "try_except"): 1, ("from . import q", "in_function"): 1,
        ("from a.b.c import D", "top_level"): 1,
    }


def test_extract_imports_never_running_branches():
    # 15 Nov fix: `if False:` was tagged eager, `if not TYPE_CHECKING:` was tagged type-only
    src = (b"import typing\n"
           b"if False:\n    from a import A\n"
           b"if not TYPE_CHECKING:\n    from b import B\nelse:\n    from c import C\n"
           b"if typing.TYPE_CHECKING:\n    from d import D\nelse:\n    from e import E\n"
           b"if (TYPE_CHECKING):\n    from f import F\n"
           b"if not TYPE_CHECKING:\n    pass\nelif x:\n    from g import G\n"
           b"if sys.version_info >= (3, 11):\n    from h import H\n"
           b"if TYPE_CHECKING and x:\n    from i import I\n"
           b"if not TYPE_CHECKING and x:\n    from j import J\n"
           b"def f():\n    if False:\n        from k import K\n")
    imps, err = mine.extract_imports(src)
    assert not err
    assert dict(imps) == {
        ("import typing", "top_level"): 1,
        ("from a import A", "type_checking"): 1,
        ("from b import B", "top_level"): 1, ("from c import C", "type_checking"): 1,
        ("from d import D", "type_checking"): 1, ("from e import E", "top_level"): 1,
        ("from f import F", "type_checking"): 1,
        ("from g import G", "type_checking"): 1,
        ("from h import H", "top_level"): 1,
        ("from i import I", "type_checking"): 1,
        ("from j import J", "top_level"): 1,
        ("from k import K", "in_function+type_checking"): 1,
    }


@pytest.mark.parametrize("cond, side", [
    ("TYPE_CHECKING", "body"), ("typing.TYPE_CHECKING", "body"), ("False", "body"),
    ("( TYPE_CHECKING )", "body"), ("not TYPE_CHECKING", "else"), ("not False", "else"),
    ("not (typing.TYPE_CHECKING)", "else"), ("TYPE_CHECKING and x", "body"),
    ("not TYPE_CHECKING and x", None), ("x", None), ("sys.platform == 'win32'", None),
])
def test_never_runs(cond, side):
    assert mine.never_runs(cond) == side


def test_import_lines_match_extract_imports():
    src = (b"from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from p import A\n"
           b"def f():\n    from p import A\n\ndef g():\n    from p import (\n        A,\n    )\n")
    lines = mine.import_lines(src)
    assert lines == {("from typing import TYPE_CHECKING", "top_level"): [1],
                     ("from p import A", "type_checking"): [3],
                     ("from p import A", "in_function"): [5, 8]}
    assert {k: len(v) for k, v in lines.items()} == dict(mine.extract_imports(src)[0])


def test_split_stmt():
    assert mine.split_stmt("import a.b") == ("a.b", None, 0)
    assert mine.split_stmt("from a.b import c") == ("a.b", "c", 0)
    assert mine.split_stmt("from ..db import session") == ("db", "session", 2)
    assert mine.split_stmt("from . import q") == ("", "q", 1)
    assert mine.split_stmt("from x import *") == ("x", "*", 0)


def test_mine_small_repo(tmp_path):
    repo = make_demo(tmp_path)
    db = tmp_path / "out" / "demo.sqlite"
    con = run(repo, db)
    assert con.execute("SELECT n_parents, agent, is_fix FROM commits ORDER BY i").fetchall() == [
        (0, None, 0), (2, "claude", 0), (1, None, 1), (1, None, 0)]  # agent found on the PR
    assert dict(con.execute("SELECT key, value FROM run_info"))["n_commits"] == "4"

    a = con.execute("SELECT file_id FROM file_changes WHERE i = 0 AND path = 'pkg/a.py'").fetchone()[0]
    b = con.execute("SELECT file_id FROM file_changes WHERE i = 0 AND path = 'pkg/b.py'").fetchone()[0]
    # the rename keeps the file id, and the path history has two intervals
    assert con.execute("SELECT change, path, old_path, file_id FROM file_changes "
                       "WHERE i = 2").fetchall() == [("R", "pkg/c.py", "pkg/a.py", a)]
    assert con.execute("SELECT path, from_i, to_i FROM file_paths WHERE file_id = ? "
                       "ORDER BY from_i", (a,)).fetchall() == [("pkg/a.py", 0, 2),
                                                               ("pkg/c.py", 2, None)]
    assert con.execute("SELECT i, delta, stmt, module, name, level FROM raw_imports "
                       "WHERE file_id = ? ORDER BY i", (b,)).fetchall() == [
        (0, 1, "from . import a", "", "a", 1), (1, 1, "import sys", "sys", None, 0)]
    assert con.execute("SELECT i, delta, stmt FROM raw_imports WHERE file_id = ? AND i > 0",
                       (a,)).fetchall() == [(3, 1, "import re")]
    assert con.execute("SELECT loc_after, parse_error FROM file_changes WHERE i = 3").fetchone() \
        == (2, 0)
    con.close()
    for f in db.parent.glob("demo.sqlite*"):  # no email and no message in the database
        assert b"a@x.com" not in f.read_bytes() and b"Conflicts" not in f.read_bytes()
    assert check.main([str(repo), str(db)]) == 0


def test_stopped_run_continues(tmp_path):
    repo = make_demo(tmp_path)
    full, part = tmp_path / "full" / "demo.sqlite", tmp_path / "part" / "demo.sqlite"
    (tmp_path / "part").mkdir()
    (tmp_path / "part" / ".salt").write_text("s\n")
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / ".salt").write_text("s\n")
    run(repo, full).close()
    con = run(repo, part, "--limit", "2")
    info = dict(con.execute("SELECT key, value FROM run_info"))
    assert info["last_i"] == "1" and "finished" not in info
    con.close()
    con = run(repo, part)
    assert "finished" in dict(con.execute("SELECT key, value FROM run_info"))
    con.close()
    assert dump(part) == dump(full)


def test_deleted_then_readded_file_gets_a_new_id(tmp_path):
    repo = new_repo(tmp_path / "r")
    (repo / "x.py").write_text("import os\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add")
    git(repo, "rm", "-q", "x.py")
    git(repo, "commit", "-qm", "delete")
    (repo / "x.py").write_text("import os\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add again")
    db = tmp_path / "r.sqlite"
    con = run(repo, db)
    assert con.execute("SELECT file_id, from_i, to_i FROM file_paths WHERE path = 'x.py' "
                       "ORDER BY from_i").fetchall() == [(1, 0, 1), (2, 2, None)]
    # the delete logs the imports as removed, so the old id ends with no imports
    assert con.execute("SELECT i, file_id, delta FROM raw_imports ORDER BY i").fetchall() == [
        (0, 1, 1), (1, 1, -1), (2, 2, 1)]
    con.close()
    assert check.main([str(repo), str(db)]) == 0


def test_format_only_and_oversized_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(mine, "OVERSIZED_FILES", 2)
    repo = new_repo(tmp_path / "r")
    (repo / "a.py").write_text("import os\nx=[1,2]\n")
    (repo / "b.py").write_text("y = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "0 init")
    (repo / "a.py").write_text("import os\n\nx = [1, 2]  # reformatted\n")
    git(repo, "commit", "-qam", "1 black")
    (repo / "a.py").write_text("import os\n\nx = [1, 2, 3]\n")
    git(repo, "commit", "-qam", "2 a real change")
    for p in ("c.py", "d.py", "e.py"):
        (repo / p).write_text("z = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "3 three files")
    (repo / "b.py").write_text("y = 2\n")
    git(repo, "commit", "-qam", "4 listed in .git-blame-ignore-revs")
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    (repo / ".git-blame-ignore-revs").write_text(f"# black\n{sha}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "5 add the ignore list")
    con = run(repo, tmp_path / "r.sqlite")
    assert con.execute("SELECT is_format_only, is_oversized FROM commits ORDER BY i").fetchall() \
        == [(0, 0), (1, 0), (0, 0), (0, 1), (1, 0), (0, 0)]


def test_check_fails_on_wrong_loc(tmp_path):
    repo = make_demo(tmp_path)
    db = tmp_path / "demo.sqlite"
    run(repo, db).close()
    assert check.main([str(repo), str(db)]) == 0
    con = sqlite3.connect(db)
    con.execute("UPDATE file_changes SET loc_after = loc_after + 1 WHERE i = 3")
    con.commit()
    con.close()
    assert check.main([str(repo), str(db)]) == 1
