"""E2 (RQ2): what happens to a deferred-only pair over the project's history.

We replay the edge log commit by commit (first-parent order). A pair A -> B is in one of
three states after each commit:
  none      no import links A to B
  eager     at least one eager import (top_level or try_except) links them
  deferred  only deferred imports (in_function / type_checking) link them

An *episode* starts at the commit where the pair enters `deferred`, and ends at the first
commit where it leaves it:
  promoted  deferred -> eager   (the pair gained an eager import; any statement, not only
            the same one moved up). `hoisted` = the deferred weight also went down in that
            commit (the import was probably moved to the top), else it is a new eager import.
  removed   deferred -> none    (`by_delete` = a file deletion caused it)
  kept      still deferred at the last mined commit (censored)
A pair can have more than one episode; `episode` numbers them (1 = first). The main analysis
uses first episodes only.

Lifetime is counted three ways: commits (first-parent), calendar days, and *active commits*
(commits that changed the source file / package between start and end).

Survival: Kaplan-Meier for "leaves deferred for any reason", and Aalen-Johansen cumulative
incidence for promoted vs removed (competing risks). Both are computed here with numpy, no
extra library.

Run:
    uv run python -m deferred_imports.analysis.fate index/*.sqlite --level file [--csv out.csv]
    [--episodes episodes.csv]
"""

from __future__ import annotations

import argparse
import bisect
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from itertools import groupby
from pathlib import Path

import numpy as np

from deferred_imports.analysis.graphs import is_deferred, write_csv


def state(kinds: Counter) -> str:
    live = [k for k, w in kinds.items() if w > 0]
    if not live:
        return "none"
    return "deferred" if all(is_deferred(k) for k in live) else "eager"


def deferred_weight(kinds: Counter) -> int:
    return sum(w for k, w in kinds.items() if w > 0 and is_deferred(k))


def edge_rows(con: sqlite3.Connection, level: str):
    """(i, src, dst, kind, delta, cause) ordered by i, excluded parts already dropped."""
    if level == "package":
        return con.execute(
            """SELECT e.i, e.src_mod, e.dst_mod, e.kind, e.delta, e.cause
               FROM module_edges e
               JOIN modules s ON s.module_id = e.src_mod
               JOIN modules d ON d.module_id = e.dst_mod
               WHERE s.excluded IS NULL AND d.excluded IS NULL
               ORDER BY e.i""")
    if level == "file":
        keep = kept_files(con)
        return ((i, s, d, k, w, c) for i, s, d, k, w, c in con.execute(
            "SELECT i, src_file, dst_file, kind, delta, cause FROM file_edges ORDER BY i")
            if s in keep and d in keep and s != d)
    raise ValueError(level)


def kept_files(con: sqlite3.Connection) -> set:
    """Files that belong to a package and were never in an excluded one (tests, docs, ...)."""
    excl = {m for (m,) in con.execute("SELECT module_id FROM modules WHERE excluded IS NOT NULL")}
    seen, bad = set(), set()
    for f, m in con.execute("SELECT file_id, module_id FROM file_modules"):
        seen.add(f)
        if m in excl:
            bad.add(f)
    return seen - bad


def touches(con: sqlite3.Connection, level: str) -> dict:
    """{node: sorted list of commits that changed it}."""
    q = ("SELECT module_id, i FROM module_touches ORDER BY i" if level == "package"
         else "SELECT file_id, i FROM file_changes ORDER BY i")
    out = defaultdict(list)
    for n, i in con.execute(q):
        out[n].append(i)
    return out


def episodes(con: sqlite3.Connection, level: str) -> list[dict]:
    weights: dict = defaultdict(Counter)
    opened: dict = {}          # pair -> start info
    n_ep: Counter = Counter()  # pair -> episodes so far
    done = []
    for i, group in groupby(edge_rows(con, level), key=lambda r: r[0]):
        group = list(group)
        pairs = {(s, d) for _, s, d, *_ in group}
        before = {p: (state(weights[p]), deferred_weight(weights[p])) for p in pairs}
        deleted = set()
        for _, s, d, k, w, cause in group:
            weights[(s, d)][k] += w
            if cause == "delete":
                deleted.add((s, d))
        for p in pairs:
            (b, bdw), a = before[p], state(weights[p])
            if a == "deferred" and b != "deferred":
                n_ep[p] += 1
                kinds = [k for k, w in weights[p].items() if w > 0]
                opened[p] = {"src": p[0], "dst": p[1], "episode": n_ep[p], "start_i": i,
                             "from_state": b,
                             "type_only": all("type_checking" in k for k in kinds)}
            elif b == "deferred" and a != "deferred":
                ep = opened.pop(p)
                ep.update(end_i=i, outcome="promoted" if a == "eager" else "removed",
                          hoisted=int(a == "eager" and deferred_weight(weights[p]) < bdw),
                          by_delete=int(a == "none" and p in deleted))
                done.append(ep)
    last = con.execute("SELECT MAX(i) FROM commits").fetchone()[0]
    for ep in opened.values():
        ep.update(end_i=last, outcome="kept", hoisted=0, by_delete=0)
        done.append(ep)
    add_lifetimes(con, level, done)
    return sorted(done, key=lambda e: (e["start_i"], str(e["src"]), str(e["dst"])))


def add_lifetimes(con: sqlite3.Connection, level: str, eps: list[dict]) -> None:
    info = {i: (datetime.fromisoformat(d), a)
            for i, d, a in con.execute("SELECT i, date, is_agent FROM commits")}
    touch = touches(con, level)
    for e in eps:
        s, t = e["start_i"], e["end_i"]
        e["commits"] = t - s
        e["days"] = round((info[t][0] - info[s][0]).total_seconds() / 86400, 2)
        ts = touch.get(e["src"], [])
        e["active_commits"] = bisect.bisect_right(ts, t) - bisect.bisect_right(ts, s)
        e["start_agent"] = info[s][1]
        e["end_agent"] = info[t][1] if e["outcome"] != "kept" else None


# survival ------------------------------------------------------------------------------------

def kaplan_meier(times, events):
    """S(t) at each distinct event time: (times, survival). events: 1 = left deferred, 0 = kept."""
    t, e = np.asarray(times, float), np.asarray(events, int)
    ut = np.unique(t[e == 1])
    s, out = 1.0, []
    for u in ut:
        at_risk = np.sum(t >= u)
        s *= 1 - np.sum((t == u) & (e == 1)) / at_risk
        out.append(s)
    return ut, np.array(out)


def km_median(times, events):
    ut, s = kaplan_meier(times, events)
    below = np.nonzero(s <= 0.5)[0]
    return float(ut[below[0]]) if len(below) else None  # None = more than half never leave


def aalen_johansen(times, causes, cause):
    """Cumulative incidence of `cause` at each event time. causes: 0 = censored, else a label."""
    t, c = np.asarray(times, float), np.asarray(causes, object)
    ut = np.unique(t[c != 0])
    s, cif, out = 1.0, 0.0, []
    for u in ut:
        at_risk = np.sum(t >= u)
        d_any = np.sum((t == u) & (c != 0))
        cif += s * np.sum((t == u) & (c == cause)) / at_risk
        s *= 1 - d_any / at_risk
        out.append(cif)
    return ut, np.array(out)


def summary(db: Path, level: str, eps: list[dict] | None = None) -> dict:
    if eps is None:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        eps = episodes(con, level)
    first = [e for e in eps if e["episode"] == 1]
    out = Counter(e["outcome"] for e in first)
    n = len(first)
    t = [e["active_commits"] for e in first]
    ev = [int(e["outcome"] != "kept") for e in first]
    cause = [0 if e["outcome"] == "kept" else e["outcome"] for e in first]

    def cif_end(k):
        _, c = aalen_johansen(t, cause, k)
        return round(float(c[-1]), 4) if len(c) else 0.0

    promoted = [e for e in first if e["outcome"] == "promoted"]
    return {
        "repo": db.stem, "level": level, "episodes_all": len(eps), "pairs": n,
        "promoted": out["promoted"], "removed": out["removed"], "kept": out["kept"],
        "share_promoted": round(out["promoted"] / n, 4) if n else None,
        "share_removed": round(out["removed"] / n, 4) if n else None,
        "share_kept": round(out["kept"] / n, 4) if n else None,
        "promoted_hoisted": sum(e["hoisted"] for e in promoted),
        "removed_by_delete": sum(e["by_delete"] for e in first if e["outcome"] == "removed"),
        "type_only_pairs": sum(e["type_only"] for e in first),
        "km_median_active_commits": km_median(t, ev) if n else None,
        "cif_promoted": cif_end("promoted"), "cif_removed": cif_end("removed"),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--level", choices=["package", "file"], default="file")
    ap.add_argument("--csv", type=Path, help="per-repo summary")
    ap.add_argument("--episodes", type=Path, help="every episode of every repo, one row each")
    a = ap.parse_args(argv)
    rows, all_eps = [], []
    for db in a.dbs:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        eps = episodes(con, a.level)
        rows.append(summary(db, a.level, eps))
        all_eps += [{"repo": db.stem, **e} for e in eps]
    write_csv(rows, a.csv)
    if a.episodes and all_eps:
        write_csv(all_eps, a.episodes)


if __name__ == "__main__":
    main()
