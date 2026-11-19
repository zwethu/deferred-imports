"""E2 (RQ2) detail: what kind of change promoted a deferred file pair.

For every first-episode promotion (fate.episodes, file level) we compare the import lines of
A -> B at the start commit (all deferred) with those right after the promoting commit:

  same_name      an imported name that was deferred at the start is now imported eagerly
                 (`def f(): from b import x` ... then `from b import x` at the top)
  different_name only other names are imported eagerly (`from b import y` at the top)
  deferred_left  at least one deferred import of B is still in A after the promotion
                 (it no longer delays anything: B is loaded at startup anyway)

Run:
    uv run python -m deferred_imports.analysis.promotion_kinds index/*.sqlite [--csv out.csv]
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from deferred_imports.analysis.fate import episodes
from deferred_imports.analysis.graphs import is_deferred, write_csv
from deferred_imports.analysis.handcheck import replay_files


def kinds(con: sqlite3.Connection) -> list[dict]:
    eps = [e for e in episodes(con, "file") if e["episode"] == 1 and e["outcome"] == "promoted"]
    at = defaultdict(set)
    for e in eps:
        at[e["start_i"]].add((e["src"], e["dst"]))
        at[e["end_i"]].add((e["src"], e["dst"]))
    found, _ = replay_files(con, at)
    out = []
    for e in eps:
        p = (e["src"], e["dst"])
        start = {stmt for _, stmt, _ in found[(e["start_i"], *p)][0]}
        after = found[(e["end_i"], *p)][0]
        eager = {stmt for _, stmt, kind in after if not is_deferred(kind)}
        out.append({"src": e["src"], "dst": e["dst"], "start_i": e["start_i"], "end_i": e["end_i"],
                    "same_name": int(bool(start & eager)),
                    "deferred_left": int(any(is_deferred(kind) for _, _, kind in after))})
    return out


def summary(db: Path, rows: list[dict]) -> dict:
    c = Counter((r["same_name"], r["deferred_left"]) for r in rows)
    n = len(rows)
    return {"repo": db.stem, "promoted": n,
            "same_name_removed": c[(1, 0)], "same_name_left": c[(1, 1)],
            "different_name_removed": c[(0, 0)], "different_name_left": c[(0, 1)],
            "share_deferred_left": round((c[(1, 1)] + c[(0, 1)]) / n, 4) if n else None}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--csv", type=Path, help="per-repo summary (default: print)")
    a = ap.parse_args(argv)
    rows, total = [], Counter()
    for db in a.dbs:
        s = summary(db, kinds(sqlite3.connect(f"file:{db}?mode=ro", uri=True)))
        rows.append(s)
        total.update({k: v for k, v in s.items() if isinstance(v, int)})
    n = total["promoted"]
    rows.append({"repo": "ALL", **{k: total[k] for k in rows[0] if k not in ("repo", "share_deferred_left")},
                 "share_deferred_left": round((total["same_name_left"] + total["different_name_left"]) / n, 4)
                 if n else None})
    write_csv(rows, a.csv)


if __name__ == "__main__":
    main()
