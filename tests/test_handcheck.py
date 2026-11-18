import csv

from deferred_imports.analysis import handcheck
from deferred_imports.analysis.cycles import closing_pairs, sccs, shortest_path
from tests.test_mine import git, new_repo, run


def test_closing_pairs_and_shortest_path():
    eager, dfo = {("a", "b"), ("b", "c")}, {("c", "a"), ("a", "d")}
    full = eager | dfo
    assert closing_pairs(sccs(full), dfo) == [("c", "a")]
    assert shortest_path(full, "a", "c") == ["a", "b", "c"]
    assert shortest_path(full, "d", "a") is None


def write(repo, files):
    for p, text in files.items():
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text(text)


def test_handcheck_lists(tmp_path):
    """shop.b -> shop.a is deferred and closes a cycle (shop.a -> shop.b is eager);
    shop.c -> shop.b starts deferred and is hoisted to the top in commit 1."""
    repo = new_repo(tmp_path / "shop")
    write(repo, {
        "shop/__init__.py": "",
        "shop/a/__init__.py": "", "shop/a/x.py": "from shop.b import y\n",
        "shop/b/__init__.py": "", "shop/b/y.py": "def f():\n    from shop.a import x\n",
        "shop/c/__init__.py": "", "shop/c/z.py": "def g():\n    from shop.b import y\n",
    })
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "0 init")
    write(repo, {"shop/c/z.py": "from shop.b import y\n\ndef g():\n    pass\n"})
    git(repo, "commit", "-qam", "1 hoist")
    db = tmp_path / "shop.sqlite"
    run(repo, db).close()

    out = tmp_path / "out"
    handcheck.main([str(db), "--out", str(out)])
    with open(out / "promotions.csv", newline="") as f:
        (p,) = list(csv.DictReader(f))
    assert (p["from_package"], p["to_package"], p["hoisted"]) == ("shop.c", "shop.b", "1")
    assert p["imports_at_start"] == "shop/c/z.py: from shop.b import y  [in_function]"
    assert p["imports_after_promotion"] == "shop/c/z.py: from shop.b import y  [top_level]"
    assert p["ok (yes/no)"] == ""

    with open(out / "cycle_edges.csv", newline="") as f:
        (c,) = list(csv.DictReader(f))
    assert (c["from_package"], c["to_package"]) == ("shop.b", "shop.a")
    assert c["deferred_imports"] == "shop/b/y.py: from shop.a import x  [in_function]"
    assert c["cycle"] == "shop.b -> shop.a -> shop.b" and c["way_back_all_eager"] == "1"
    assert "shop/a/x.py: from shop.b import y  [top_level]" in c["way_back_imports"]
    assert c["deferred_since"].endswith(")") and c["checker_a_ok (yes/no)"] == ""
