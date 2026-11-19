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
    assert p["new_eager_imports"] == "shop/c/z.py: from shop.b import y  [top_level]"
    assert p["new_eager_evidence"] == p["promotion_evidence"] == ""  # no GitHub url for a test repo
    assert p["checker_a (yes/no)"] == p["checker_b (yes/no)"] == ""

    with open(out / "cycle_edges.csv", newline="") as f:
        (c,) = list(csv.DictReader(f))
    assert (c["from_package"], c["to_package"]) == ("shop.b", "shop.a")
    assert c["deferred_imports"] == "shop/b/y.py: from shop.a import x  [in_function]"
    assert c["cycle"] == "shop.b -> shop.a -> shop.b" and c["way_back_all_eager"] == "1"
    assert "shop/a/x.py: from shop.b import y  [top_level]" in c["way_back_imports"]
    assert c["deferred_since"].endswith(")") and c["checker_a (yes/no)"] == ""
    assert c["deferred_since_imports"] == "shop/b/y.py: from shop.a import x  [in_function]"

    with open(out / "promotions_lines.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(x["type"], x["where"]) for x in rows] == [
        ("deferred", "inside a function"), ("normal", "top of the file")]
    assert rows[0]["checker_a (ok?)"] == "" and rows[0]["ast_check"] == "not checked (no clone)"
    lines = [(x["role"], x["file"], x["line"], x["kind"]) for x in rows]
    assert lines == [("step 1: deferred at start", "shop/c/z.py", "", "in_function"),
                     ("step 2: new eager import", "shop/c/z.py", "", "top_level")]  # no clone: no line
    with open(out / "cycle_edges_lines.csv", newline="") as f:
        roles = [x["role"] for x in csv.DictReader(f)]
    assert roles == ["step 1: deferred import", "step 2: way back shop.a -> shop.b (eager)",
                     "step 3: deferred since"]


def test_find_line():
    src = ("import os\nfrom a.b import (\n    c,\n    d,\n)\n"
           "def f():\n    from a.b import d\n    import x.y as z\n"
           "from .m import n\n")
    assert handcheck.find_line(src, "a.b", "d", 0, "top_level") == 2      # inside ( ... )
    assert handcheck.find_line(src, "a.b", "d", 0, "in_function") == 7    # the indented one
    assert handcheck.find_line(src, "x.y", None, 0, "in_function") == 8
    assert handcheck.find_line(src, "m", "n", 1, "top_level") == 9
    assert handcheck.find_line(src, "a.b", "q", 0, "top_level") is None
    long = "from p import (\n" + "".join(f"    n{k},\n" for k in range(40)) + ")\n"
    assert handcheck.find_line(long, "p", "n39", 0, "top_level") == 1   # more than 15 names
    twice = "def f():\n    from p import g\n\ndef h():\n    from p import g\n"
    assert handcheck.find_line(twice, "p", "g", 0, "in_function", nth=1) == 5  # second copy
    assert handcheck.find_line(twice, "p", "g", 0, "in_function", nth=0) == 2
    cont = "import os\nfrom p import a, \\\n    b\n"
    assert handcheck.find_line(cont, "p", "b", 0, "top_level") == 2     # backslash continuation


def test_where_and_ast_imports():
    assert handcheck.where("in_function+try_except") == \
        "inside a function + inside try/except (still runs at load)"
    src = (b"import os\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from p import A\n"
           b"def f():\n    from q import B\n")
    got = handcheck.ast_imports(src)
    assert got[4] == [("from p import A", "type_checking")]
    assert got[6] == [("from q import B", "in_function")]
    assert handcheck.ast_imports(b"print 'python 2'\n") is None
