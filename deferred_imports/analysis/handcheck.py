"""R3 hand-check lists: random samples of promotions (E2) and of deferred-only edges that close a
cycle (E3), written so a person can check each row on GitHub.

    uv run python -m deferred_imports.analysis.handcheck index/*.sqlite --out handcheck [--n 30]

Writes two CSV files (they open in Excel or Google Sheets):

  promotions.csv   first-episode promotions: package A -> B was linked only by deferred imports,
                   then gained an eager import. Columns: the two packages, the commit where the
                   pair became deferred and the commit where it was promoted (SHA, date, GitHub
                   link), lifetimes, and the exact import lines linking A to B after each of the
                   two commits.
  cycle_edges.csv  deferred-only pairs A -> B at the pinned commit where B can reach A again, so
                   the deferred import closes a cycle. Columns: the deferred import lines, the
                   commit where the pair became deferred, and the shortest way back
                   B -> ... -> A, with the import lines of each step.

Each file ends with empty columns for the checkers. What to decide for each row:
  promotions   ok = yes if, at the start commit, A uses B only inside functions or under
               TYPE_CHECKING, and the promoting commit adds an import of B that runs when A loads.
  cycle edges  ok = yes if A really imports B only in a deferred way at the pinned commit, and
               every step of the way back is a real import.

Both lists are at the package level (module pairs), as in the research plan. The samples are drawn
from all given repositories pooled, with a fixed --seed, so the same command gives the same rows.
The import lines are found by replaying the edge build (edges.Graph), so they are exactly the
imports the miner counted.
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

from deferred_imports.analysis.cycles import closing_pairs, sccs, shortest_path
from deferred_imports.analysis.fate import episodes
from deferred_imports.analysis.graphs import pair_weights, split_pairs
from deferred_imports.mining.edges import Graph, _by_commit, settings_of

CORPUS = [Path("corpus/paper-corpus.csv"), Path("corpus/repos.csv")]
MAX_LINES = 6  # import lines shown per package pair; the rest are counted


def repo_urls() -> dict[str, str]:
    urls: dict[str, str] = {}
    here = Path(__file__).resolve().parents[2]
    for p in CORPUS:
        for path in (p, here / p):
            if path.exists():
                with open(path, newline="") as f:
                    for r in csv.DictReader(f):
                        urls.setdefault(r["name"], r["url"].rstrip("/"))
                break
    return urls


def stmt_text(module: str, name: str | None, level: int) -> str:
    return f"import {module}" if name is None else f"from {'.' * level}{module} import {name}"


def links(g: Graph, sm: int, dm: int) -> list[str]:
    """The import lines that link package sm to package dm in g's current state."""
    out = []
    for fid, m in list(g.mod_of.items()):
        if m != sm or fid not in g.path:
            continue
        for (module, name, level, kind), n in g.imports.get(fid, {}).items():
            if n <= 0:
                continue
            dst = g.resolve(fid, module, name, level)[0]
            if dst is not None and dst != fid and g.mod_of.get(dst) == dm:
                line = f"{g.path[fid]}: {stmt_text(module, name, level)}  [{kind}]"
                out += [line] * n
    return sorted(out)


def show(lines: list[str]) -> str:
    extra = len(lines) - MAX_LINES
    return "\n".join(lines[:MAX_LINES] + ([f"... and {extra} more"] if extra > 0 else []))


def replay(con: sqlite3.Connection, at: dict[int, set]) -> tuple[dict, Graph]:
    """Rebuild the graph commit by commit. Returns {(i, sm, dm): import lines after commit i}
    for every pair asked for in `at`, and the graph at the last commit."""
    g = Graph(*settings_of(con))
    found = {}
    for i, changes, imports in _by_commit(con):
        g.step(i, changes, imports)
        for sm, dm in at.get(i, ()):
            found[(i, sm, dm)] = links(g, sm, dm)
    return found, g


class Repo:
    def __init__(self, db: Path, urls: dict[str, str]):
        self.db, self.name = db, db.stem
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.url = urls.get(self.name, "")
        self.mod = dict(self.con.execute("SELECT module_id, name FROM modules"))
        self.commit = {i: (sha, date[:10]) for i, sha, date in
                       self.con.execute("SELECT i, sha, date FROM commits")}
        self.pinned = self.con.execute("SELECT value FROM run_info WHERE key = 'pinned_sha'"
                                       ).fetchone()[0]
        self._eps = None

    def episodes(self) -> list[dict]:
        if self._eps is None:
            self._eps = episodes(self.con, "package")
        return self._eps

    def name_of(self, m: int) -> str:
        return self.mod[m] or "(repository root)"

    def sha(self, i: int) -> str:
        return self.commit[i][0][:10]

    def link(self, i: int) -> str:
        return f"{self.url}/commit/{self.commit[i][0]}" if self.url else ""


def sample(items: list, n: int, seed: int) -> list:
    if n <= 0 or n >= len(items):
        return items
    return random.Random(seed).sample(items, n)


def promotions(repos: list[Repo], n: int, seed: int) -> list[dict]:
    pool = [(r, e) for r in repos for e in r.episodes()
            if e["episode"] == 1 and e["outcome"] == "promoted"]
    picked = sample(pool, n, seed)
    by_repo = defaultdict(list)
    for r, e in picked:
        by_repo[r.name].append((r, e))
    rows = []
    for items in by_repo.values():
        r = items[0][0]
        at = defaultdict(set)
        for _, e in items:
            at[e["start_i"]].add((e["src"], e["dst"]))
            at[e["end_i"]].add((e["src"], e["dst"]))
        found, _ = replay(r.con, at)
        for _, e in items:
            s, t, p = e["start_i"], e["end_i"], (e["src"], e["dst"])
            rows.append({
                "repo": r.name,
                "from_package": r.name_of(e["src"]), "to_package": r.name_of(e["dst"]),
                "deferred_since": f"{r.sha(s)} ({r.commit[s][1]})",
                "promoted_at": f"{r.sha(t)} ({r.commit[t][1]})",
                "commits": e["commits"], "active_commits": e["active_commits"],
                "days": e["days"], "hoisted": e["hoisted"], "type_only": int(e["type_only"]),
                "from_state": e["from_state"],
                "imports_at_start": show(found.get((s, *p), [])),
                "imports_after_promotion": show(found.get((t, *p), [])),
                "start_commit_url": r.link(s), "promotion_commit_url": r.link(t),
            })
    return finish(rows, ["checker", "ok (yes/no)", "note"])


def cycle_edges(repos: list[Repo], n: int, seed: int) -> list[dict]:
    pool = []
    for r in repos:
        eager, dfo = split_pairs(pair_weights(r.con, "package"))
        full = eager | dfo
        for a, b in closing_pairs(sccs(full), dfo):
            pool.append((r, a, b, shortest_path(full, b, a), eager))
    picked = sample(pool, n, seed)
    by_repo = defaultdict(list)
    for item in picked:
        by_repo[item[0].name].append(item)
    rows = []
    for items in by_repo.values():
        r = items[0][0]
        _, g = replay(r.con, {})
        since = {(e["src"], e["dst"]): e["start_i"] for e in r.episodes()
                 if e["outcome"] == "kept"}
        last = max(r.commit)
        for _, a, b, path, eager in items:
            hops = list(pairwise(path))
            back = []
            for x, y in hops:
                kind = "eager" if (x, y) in eager else "deferred"
                back.append(f"{r.name_of(x)} -> {r.name_of(y)} ({kind}):")
                back += ["    " + line for line in show(links(g, x, y)).split("\n")]
            s = since.get((a, b))
            rows.append({
                "repo": r.name,
                "from_package": r.name_of(a), "to_package": r.name_of(b),
                "deferred_imports": show(links(g, a, b)),
                "cycle": " -> ".join(r.name_of(x) for x in [a, *path]),
                "cycle_length": len(path),
                "way_back_all_eager": int(all((x, y) in eager for x, y in hops)),
                "way_back_imports": "\n".join(back),
                "deferred_since": f"{r.sha(s)} ({r.commit[s][1]})" if s is not None else "",
                "deferred_since_url": r.link(s) if s is not None else "",
                "pinned_tree_url": f"{r.url}/tree/{r.pinned}" if r.url else "",
                "last_commit": r.sha(last),
            })
    return finish(rows, ["checker_a_ok (yes/no)", "checker_b_ok (yes/no)", "note"])


def finish(rows: list[dict], blank: list[str]) -> list[dict]:
    rows.sort(key=lambda x: (x["repo"], x["from_package"], x["to_package"]))
    return [{"id": k, **row, **{c: "" for c in blank}} for k, row in enumerate(rows, 1)]


def write(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("handcheck"))
    ap.add_argument("--n", type=int, default=30, help="rows per list; 0 = all (default 30)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    urls = repo_urls()
    repos = [Repo(db, urls) for db in a.dbs]
    p = promotions(repos, a.n, a.seed)
    write(p, a.out / "promotions.csv")
    c = cycle_edges(repos, a.n, a.seed)
    write(c, a.out / "cycle_edges.csv")
    print(f"{len(p)} promotions -> {a.out / 'promotions.csv'}")
    print(f"{len(c)} cycle-closing edges -> {a.out / 'cycle_edges.csv'}")


if __name__ == "__main__":
    main()
