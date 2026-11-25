"""RQ3 split by cycles: do deferred-only pairs that sit on an import cycle end differently?

For every episode of a deferred-only file pair A -> B (from analysis.fate), this records
  on_cycle_start  A and B are in the same strongly connected component (2+ files) of the FULL
                  file graph (eager and deferred imports) right after the commit where the
                  episode started, i.e. B can reach A again, so the deferred import closes a cycle
  on_cycle_last   the same test at the last mined commit, only for episodes still open there
and then compares on-cycle and off-cycle first episodes: outcome shares and the Kaplan-Meier
median duration in days (still-deferred episodes are censored), per kind and overall.

    uv run python -m deferred_imports.analysis.oncycle index/*.sqlite --out out/oncycle [--jobs 4]

Writes out/oncycle/episodes.csv (one row per episode) and out/oncycle/summary.csv.
The graph at each start commit is rebuilt with graphs.pair_weights (same filters as E1/E3).
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median

from deferred_imports.analysis.cycles import sccs
from deferred_imports.analysis.fate import episodes, km_median
from deferred_imports.analysis.graphs import last_i, pair_weights


def comp_index(pairs) -> dict:
    """file -> SCC number, for files in an SCC with 2+ files."""
    return {n: k for k, c in enumerate(sccs(pairs)) for n in c}


def on_cycle(comp: dict, a, b) -> bool:
    return a in comp and comp.get(a) == comp.get(b)


def label(eps_with_flags: list[dict], con: sqlite3.Connection) -> None:
    """Add on_cycle_start (True/False, None if the pair is not in the graph) and on_cycle_last."""
    starts = sorted({e["start_i"] for e in eps_with_flags})
    by_start: dict = {}
    for e in eps_with_flags:
        by_start.setdefault(e["start_i"], []).append(e)
    for i in starts:
        w = pair_weights(con, "file", at=i)
        comp = comp_index(w)
        for e in by_start[i]:
            e["on_cycle_start"] = (on_cycle(comp, e["src"], e["dst"])
                                   if (e["src"], e["dst"]) in w else None)
    w = pair_weights(con, "file", at=last_i(con))
    comp = comp_index(w)
    for e in eps_with_flags:
        e["on_cycle_last"] = on_cycle(comp, e["src"], e["dst"]) if e["outcome"] == "kept" else None


def run_one(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    eps = episodes(con, "file")
    label(eps, con)
    keep = ("src", "dst", "episode", "start_i", "end_i", "type_only", "outcome", "days",
            "on_cycle_start", "on_cycle_last")
    return [{"repo": db.stem, **{k: e[k] for k in keep}} for e in eps]


def group_summary(rows: list[dict]) -> list[dict]:
    """Outcome shares and KM median days for first episodes, by kind x on/off cycle at start."""
    first = [r for r in rows if r["episode"] == 1 and r["on_cycle_start"] is not None]
    out = []
    for kind, fk in (("in-function", False), ("type-only", True), ("all", None)):
        for cyc in (True, False):
            g = [r for r in first if r["on_cycle_start"] == cyc and (fk is None or r["type_only"] == fk)]
            n = len(g)
            if not n:
                continue
            c = {o: sum(r["outcome"] == o for r in g) for o in ("promoted", "removed", "kept")}
            med = km_median([r["days"] for r in g], [int(r["outcome"] != "kept") for r in g])
            out.append({"kind": kind, "on_cycle_at_start": cyc, "episodes": n,
                        **{f"{o}_pct": round(100 * v / n, 1) for o, v in c.items()},
                        "km_median_days": None if med is None else round(med)})
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/oncycle"))
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    rows: list[dict] = []
    with ProcessPoolExecutor(a.jobs) as pool:
        for db, part in zip(a.dbs, pool.map(run_one, a.dbs)):
            print(f"{db.stem}: {len(part)} episodes", flush=True)
            rows += part
    write_csv(rows, a.out / "episodes.csv")
    summ = group_summary(rows)
    write_csv(summ, a.out / "summary.csv")
    for s in summ:
        print(s)
    # quick view: pairs still deferred-only at the last commit, age by cycle status there
    open_ = [r for r in rows if r["outcome"] == "kept"]
    for cyc in (True, False):
        g = [r["days"] for r in open_ if r["on_cycle_last"] == cyc]
        print(f"still deferred at last commit, on cycle there={cyc}: n={len(g)}, "
              f"median age={median(g) if g else None} days")


if __name__ == "__main__":
    main()
