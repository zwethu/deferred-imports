"""E1 (RQ1): how much of the dependency graph exists only through deferred imports.

Deferred = the import kind contains `in_function` or `type_checking` (it does not run when the
module loads). `top_level` and `try_except` are eager: a top-level try/except import still runs
at load time, so it is kept apart and NOT counted as deferred.

Two graph levels:
  package  nodes are the miner's modules (folders with __init__.py), from `module_edges`
  file     nodes are .py files (Python modules), from `file_edges`
Files in excluded modules (tests, docs, migrations, ...) are dropped at both levels.

A pair A -> B is
  eager          if at least one eager import links them,
  deferred-only  if only deferred imports link them.

Run:
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite [--level file] [--csv out.csv]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFERRED_TAGS = ("in_function", "type_checking")


def is_deferred(kind: str) -> bool:
    return any(t in kind.split("+") for t in DEFERRED_TAGS)


def last_i(con: sqlite3.Connection) -> int:
    return con.execute("SELECT MAX(i) FROM commits").fetchone()[0]


def pair_weights(con: sqlite3.Connection, level: str = "package", at: int | None = None) -> dict:
    """{(src, dst): Counter(kind -> weight)} for the graph after commit `at` (default: last)."""
    at = last_i(con) if at is None else at
    if level == "package":
        rows = con.execute(
            """SELECT e.src_mod, e.dst_mod, e.kind, SUM(e.delta)
               FROM module_edges e
               JOIN modules s ON s.module_id = e.src_mod
               JOIN modules d ON d.module_id = e.dst_mod
               WHERE e.i <= ? AND s.excluded IS NULL AND d.excluded IS NULL
               GROUP BY e.src_mod, e.dst_mod, e.kind""", (at,))
    elif level == "file":
        # module of each file at `at`, to drop files in excluded modules
        mod = {f: m for f, m in con.execute(
            "SELECT file_id, module_id FROM file_modules WHERE from_i <= ? AND (to_i IS NULL OR to_i > ?)",
            (at, at))}
        excl = {m for (m,) in con.execute("SELECT module_id FROM modules WHERE excluded IS NOT NULL")}
        keep = {f for f, m in mod.items() if m not in excl}
        rows = [(s, d, k, w) for s, d, k, w in con.execute(
            """SELECT src_file, dst_file, kind, SUM(delta) FROM file_edges WHERE i <= ?
               GROUP BY src_file, dst_file, kind""", (at,))
                if s in keep and d in keep and s != d]
    else:
        raise ValueError(level)
    out: dict = defaultdict(Counter)
    for s, d, k, w in rows:
        if w > 0:
            out[(s, d)][k] += w
    return dict(out)


def split_pairs(weights: dict) -> tuple[set, set]:
    """(eager pairs, deferred-only pairs)."""
    eager, deferred_only = set(), set()
    for pair, kinds in weights.items():
        if any(not is_deferred(k) for k in kinds):
            eager.add(pair)
        else:
            deferred_only.add(pair)
    return eager, deferred_only


def summary(db: Path, level: str) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    w = pair_weights(con, level)
    eager, dfo = split_pairs(w)
    type_only = {p for p in dfo if all("type_checking" in k for k in w[p])}
    imports = Counter()
    for (k, n) in con.execute("SELECT kind, SUM(delta) FROM raw_imports GROUP BY kind"):
        imports["deferred" if is_deferred(k) else "eager"] += n
    n_pairs = len(eager) + len(dfo)
    return {
        "repo": db.stem, "level": level, "last_i": last_i(con),
        "imports_eager": imports["eager"], "imports_deferred": imports["deferred"],
        "pairs": n_pairs, "pairs_eager": len(eager), "pairs_deferred_only": len(dfo),
        "pairs_type_only": len(type_only),
        "share_deferred_only": round(len(dfo) / n_pairs, 4) if n_pairs else None,
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--level", choices=["package", "file"], default="package")
    ap.add_argument("--csv", type=Path)
    a = ap.parse_args(argv)
    rows = [summary(db, a.level) for db in a.dbs]
    out = open(a.csv, "w", newline="") if a.csv else sys.stdout
    w = csv.DictWriter(out, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)


if __name__ == "__main__":
    main()
