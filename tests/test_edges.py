import sqlite3

from deferred_imports.mining import check, edges
from deferred_imports.mining.edges import Graph
from deferred_imports.mining.mine import split_stmt
from tests.test_mine import git, new_repo, run

SHOP = ["shop/__init__.py", "shop/db/__init__.py", "shop/db/session.py", "shop/db/models.py",
        "shop/orders/__init__.py", "shop/orders/cart.py", "shop/orders/views.py"]


def graph(files: dict, roots=("",), py2_until=-1):
    """A graph with every file added in commit 0. files: path -> import statements."""
    g = Graph(list(roots), py2_until)
    ids = {p: k for k, p in enumerate(sorted(files), 1)}
    imports = sorted(((ids[p], 1, s, *split_stmt(s), "top_level")
                      for p, stmts in files.items() for s in stmts), key=lambda r: (r[0], r[2]))
    g.step(0, [(ids[p], "A", p, None) for p in sorted(files)], imports)
    return g, ids


def status(g, ids, importer, stmt):
    dst, _, st = g.resolve(ids[importer], *split_stmt(stmt))
    path = {v: k for k, v in ids.items()}.get(dst)
    return path, st


def test_import_forms():
    g, ids = graph({p: [] for p in SHOP})
    v = "shop/orders/views.py"
    assert status(g, ids, v, "from ..db import session") == ("shop/db/session.py", "internal")
    assert status(g, ids, v, "from . import cart") == ("shop/orders/cart.py", "internal")
    assert status(g, ids, v, "from .cart import Cart") == ("shop/orders/cart.py", "internal")
    assert status(g, ids, v, "import shop.db.models") == ("shop/db/models.py", "internal")
    # `from pkg import name`: the submodule if there is one, else the package's __init__.py
    assert status(g, ids, v, "from shop.db import session") == ("shop/db/session.py", "internal")
    assert status(g, ids, v, "from shop.db import Base") == ("shop/db/__init__.py", "internal")
    assert status(g, ids, v, "import requests") == (None, "external")
    assert status(g, ids, v, "import json") == (None, "external")
    assert status(g, ids, v, "from shop.missing import x") == (None, "unresolved")
    assert status(g, ids, v, "from .... import x") == (None, "unresolved")  # above the root
    assert status(g, ids, "shop/orders/__init__.py", "from . import x") == (
        "shop/orders/__init__.py", "self")


def test_namespace_package_under_src():
    # like poetry: src/poetry has no __init__.py, and poetry.core comes from another package
    files = {"src/poetry/utils/__init__.py": [], "src/poetry/utils/env.py": [],
             "src/poetry/factory.py": [], "tests/test_env.py": []}
    g, ids = graph(files, roots=["", "src"])
    f = "src/poetry/factory.py"
    assert status(g, ids, f, "from poetry.utils.env import Env") == (
        "src/poetry/utils/env.py", "internal")
    assert status(g, ids, "tests/test_env.py", "from poetry.utils import env") == (
        "src/poetry/utils/env.py", "internal")
    assert status(g, ids, f, "from poetry.core.packages import Package") == (None, "external")
    assert status(g, ids, f, "from poetry.utils.missing import x") == (None, "unresolved")
    assert g.module_info[g.modules["poetry.utils"]] == ("poetry.utils", None)


def test_standard_library_is_not_shadowed_from_outside():
    files = {"tests/logging/__init__.py": [], "tests/test_x.py": [], "app/__init__.py": [],
             "app/run.py": []}
    g, ids = graph(files, roots=["", "tests"])
    assert status(g, ids, "app/run.py", "import logging") == (None, "external")
    # inside tests/, Python itself would find tests/logging first
    assert status(g, ids, "tests/test_x.py", "import logging") == (
        "tests/logging/__init__.py", "internal")


def test_script_sees_its_own_directory():
    g, ids = graph({"scripts/release.py": [], "scripts/helpers.py": []})
    assert status(g, ids, "scripts/release.py", "import helpers") == (
        "scripts/helpers.py", "internal")


def test_python2_implicit_relative_only_before_the_cutoff():
    files = {"pkg/__init__.py": [], "pkg/models.py": [], "pkg/views.py": ["import models"]}
    g, ids = graph(files, py2_until=5)
    assert status(g, ids, "pkg/views.py", "import models") == ("pkg/models.py", "implicit")
    assert g.out[ids["pkg/views.py"]] == {(ids["pkg/models.py"], "top_level"): 1}
    g.step(6, [(ids["pkg/views.py"], "M", "pkg/views.py", None)], [])  # Python 3 from here
    assert status(g, ids, "pkg/views.py", "import models") == (None, "external")
    assert ids["pkg/views.py"] not in g.out


def test_excluded_packages_get_no_module_edges():
    files = {"shop/__init__.py": [], "shop/db/__init__.py": [], "shop/db/session.py": [],
             "tests/__init__.py": ["import shop.db.session"]}
    g, _ = graph(files)
    assert g.file_weights()  # the file edge is kept
    assert g.module_weights() == {}  # but tests is excluded from the module graph
    assert g.module_info[g.modules["tests"]] == ("tests", "tests")


def test_crossing_repair_and_move_in_a_real_repo(tmp_path):
    repo = new_repo(tmp_path / "shop")
    for p in SHOP + ["shop/billing/__init__.py", "tests/__init__.py"]:
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text("")
    (repo / "shop/orders/cart.py").write_text("from shop.db import session\n")
    (repo / "tests/__init__.py").write_text("import shop.orders.cart\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "0 init")
    (repo / "shop/db/models.py").write_text("from shop.orders.cart import Cart\n")
    git(repo, "commit", "-qam", "1 db imports orders: a crossing")
    (repo / "shop/db/models.py").write_text("x = 1\n")
    git(repo, "commit", "-qam", "2 removed again: a repair")
    git(repo, "mv", "shop/orders/cart.py", "shop/billing/cart.py")
    git(repo, "commit", "-qm", "3 cart moves to billing")
    db = tmp_path / "shop.sqlite"
    con = run(repo, db)
    rows = con.execute(
        "SELECT e.i, s.name, d.name, e.delta, e.cause FROM module_edges e "
        "JOIN modules s ON s.module_id = e.src_mod JOIN modules d ON d.module_id = e.dst_mod "
        "ORDER BY e.i, s.name, d.name").fetchall()
    assert rows == [
        (0, "shop.orders", "shop.db", 1, "import"),
        (1, "shop.db", "shop.orders", 1, "import"),    # crossing
        (2, "shop.db", "shop.orders", -1, "import"),   # repair
        (3, "shop.billing", "shop.db", 1, "move"),     # a move is never a repair
        (3, "shop.orders", "shop.db", -1, "move"),
    ]
    excluded = dict(con.execute("SELECT name, excluded FROM modules"))
    assert excluded["tests"] == "tests" and excluded["shop.db"] is None
    touches = con.execute("SELECT m.name FROM module_touches t JOIN modules m "
                          "ON m.module_id = t.module_id WHERE t.i = 3").fetchall()
    assert touches == [("shop.billing",)]
    # tests/__init__.py still imports shop.orders.cart, which the move broke. A problems row is
    # written only when an import line is added, so this one shows in the run_info count.
    assert con.execute("SELECT i, kind, detail FROM problems").fetchall() == []
    info = dict(con.execute("SELECT key, value FROM run_info"))
    assert info["n_unresolved_imports"] == "1" and info["n_dangling_edges"] == "0"
    con.close()
    assert check.main([str(repo), str(db)]) == 0


def test_build_can_run_again(tmp_path):
    repo = new_repo(tmp_path / "r")
    (repo / "a").mkdir()
    (repo / "a/__init__.py").write_text("")
    (repo / "b").mkdir()
    (repo / "b/__init__.py").write_text("import a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    db = tmp_path / "r.sqlite"
    run(repo, db).close()
    con = sqlite3.connect(db)
    first = con.execute("SELECT * FROM module_edges").fetchall()
    edges.build(con)  # rebuilding gives the same rows, not twice as many
    assert con.execute("SELECT * FROM module_edges").fetchall() == first == [
        (0, 2, 1, 1, "top_level", "import")]


def test_package_at_the_repository_root():
    """A root __init__.py makes the root a package (module ''); its files belong to it."""
    files = {"__init__.py": [], "lint.py": ["from core import utils"],
             "core/__init__.py": [], "core/utils.py": []}
    g, ids = graph(files)
    root = g.modules[""]
    assert g.mod_of[ids["lint.py"]] == root
    assert g.module_weights() == {("", "core", "top_level"): 1}
