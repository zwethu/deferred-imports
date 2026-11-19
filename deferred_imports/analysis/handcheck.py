"""R3 hand-check lists: random samples of promotions (E2) and of deferred-only edges that close a
cycle (E3), written so a person can check each row on GitHub.

    uv run python -m deferred_imports.analysis.handcheck index/*.sqlite --out handcheck [--n 30]
        [--level file|package] [--clones ../clones]

--level file (the default, the level of the paper's results) writes one row per import line:
each pair gets an id, and its rows are the exact import lines our miner counted, with the file,
the line number, the commit and a GitHub link that opens that line. A checker writes yes/no per
line. The line number is found by reading the file at that commit from the local clone
(--clones) with the miner's own parser; `auto_check` says whether the line was found there.
--level package writes the older package-level lists described below.

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
import subprocess
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from deferred_imports.analysis.cycles import closing_pairs, sccs, shortest_path
from deferred_imports.analysis.fate import episodes
from deferred_imports.analysis.graphs import is_deferred, pair_weights, split_pairs
from deferred_imports.mining.edges import Graph, _by_commit, settings_of
from deferred_imports.mining.mine import PARSER, WALK_INTO, _clean, _kind, _name, never_runs

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
        self._eps: dict[str, list] = {}

    def episodes(self, level: str = "package") -> list[dict]:
        if level not in self._eps:
            self._eps[level] = episodes(self.con, level)
        return self._eps[level]

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


# ---------------------------------------------------------------- file level (the paper's level)

WHERE = {"in_function": "inside a function",
         "type_checking": "under if TYPE_CHECKING (never runs)",
         "try_except": "inside try/except (still runs at load)",
         "top_level": "top of the file"}
LINE_COLS = ["ok (yes/no)", "note"]


def where(kind: str) -> str:
    tags = kind.split("+")
    if "try_except" in tags and len(tags) > 1:  # inside a function too: it does not run at load
        return " + ".join(WHERE[t] if t != "try_except" else "inside try/except" for t in tags)
    return " + ".join(WHERE[t] for t in tags)


def file_links(g: Graph, s: int, d: int) -> list[tuple[str, str, str]]:
    """(path of s, import statement, kind) for every import in file s that the miner resolved
    to file d, in g's current state. An import counted twice is listed twice."""
    if s not in g.path:
        return []
    out = []
    for (module, name, level, kind), n in g.imports.get(s, {}).items():
        if n > 0 and g.resolve(s, module, name, level)[0] == d:
            out += [(g.path[s], stmt_text(module, name, level), kind)] * n
    return sorted(out)


def replay_files(con: sqlite3.Connection, at: dict[int, set]) -> tuple[dict, Graph]:
    """Like replay(), at file level: {(i, s, d): (file_links, path of d)} after commit i."""
    g = Graph(*settings_of(con))
    found = {}
    for i, changes, imports in _by_commit(con):
        g.step(i, changes, imports)
        for s, d in at.get(i, ()):
            found[(i, s, d)] = (file_links(g, s, d), g.path.get(d, ""))
    return found, g


def import_lines(src: bytes) -> dict[tuple[str, str], list[int]]:
    """{(import, kind): [line numbers]}, with the same walk and kinds as mine.extract_imports."""
    out: dict = defaultdict(list)
    todo = [(PARSER.parse(src).root_node, ())]
    while todo:
        node, ctx = todo.pop()
        t, line = node.type, node.start_point[0] + 1
        if t == "import_statement":
            for n in node.children_by_field_name("name"):
                out[(f"import {_name(n)}", _kind(ctx))].append(line)
        elif t == "import_from_statement":
            mod = _clean(node.child_by_field_name("module_name"))
            names = node.children_by_field_name("name")
            if not names:
                out[(f"from {mod} import *", _kind(ctx))].append(line)
            for n in names:
                out[(f"from {mod} import {_name(n)}", _kind(ctx))].append(line)
        elif t in WALK_INTO:
            if t == "if_statement":
                cond = node.child_by_field_name("condition")
                side = never_runs(cond.text.decode("utf-8", "replace")) if cond else None
                if side:
                    body = node.child_by_field_name("consequence")
                    for c in node.children:
                        dead = (c == body) if side == "body" else \
                            c.type in ("elif_clause", "else_clause")
                        todo.append((c, ctx + ("type_checking",) if dead else ctx))
                    continue
            sub = ctx + (t,) if t in ("function_definition", "try_statement") else ctx
            for c in node.children:
                todo.append((c, sub))
    return {k: sorted(v) for k, v in out.items()}


class Lines:
    """Line numbers of import statements, read from a local clone (None = no clone)."""

    def __init__(self, clone: Path | None):
        self.clone = clone if clone is not None and (clone / ".git").exists() else None
        self.cache: dict = {}
        self.text: dict = {}

    def find(self, sha: str, path: str) -> dict | None:
        if self.clone is None:
            return None
        if (sha, path) not in self.cache:
            try:
                src = subprocess.run(["git", "-C", str(self.clone), "show", f"{sha}:{path}"],
                                     check=True, capture_output=True).stdout
                self.cache[(sha, path)] = import_lines(src)
                self.text[(sha, path)] = src.decode("utf-8", "replace").splitlines()
            except subprocess.CalledProcessError:
                self.cache[(sha, path)] = {}
        return self.cache[(sha, path)]

    def code(self, sha: str, path: str, line: int) -> str:
        """The source line itself (what a checker sees on GitHub), e.g. with its `as` alias."""
        text = self.text.get((sha, path), [])
        return text[line - 1].strip() if 0 < line <= len(text) else ""


def line_rows(r: Repo, lines: Lines, i: int, role: str,
              found: list[tuple[str, str, str]]) -> list[dict]:
    """One row per import line, with its line number and a GitHub link to it."""
    sha = r.commit[i][0]
    rows, used = [], Counter()
    for path, stmt, kind in found:
        known = lines.find(sha, path)
        cands = (known or {}).get((stmt, kind), [])
        k = used[(path, stmt, kind)]
        used[(path, stmt, kind)] += 1
        line = cands[k] if k < len(cands) else ""
        check = "no clone" if known is None else ("line found" if line else "NOT found")
        blob = f"{r.url}/blob/{sha}/{path}" if r.url else ""
        rows.append({
            "role": role, "type": "deferred" if is_deferred(kind) else "normal",
            "where": where(kind), "import": stmt, "file": path, "line": line,
            "code_at_line": lines.code(sha, path, line) if line else "",
            "commit": sha[:10], "link": f"{blob}#L{line}" if blob and line else blob,
            "auto_check": check, "kind": kind,
        })
    return merge_same_line(rows)


def merge_same_line(rows: list[dict]) -> list[dict]:
    """`from x import a, b, c` is 3 imports but 1 line to check: keep one row per source line
    (and kind), with the imported names joined by "; "."""
    out: dict = {}
    for row in rows:
        key = (row["file"], row["line"], row["kind"]) if row["line"] else id(row)
        if key in out:
            out[key]["import"] += "; " + row["import"]
        else:
            out[key] = dict(row)
    return sorted(out.values(), key=lambda x: (x["file"], x["line"] or 0))


def number(groups: list[tuple[dict, list[dict]]]) -> list[dict]:
    """Sort pairs, give each an id, add the empty checker columns."""
    groups.sort(key=lambda x: (x[0]["repo"], x[0]["from_file"], x[0]["to_file"]))
    out = []
    for k, (head, rows) in enumerate(groups, 1):
        out += [{"id": k, **head, **row, **{c: "" for c in LINE_COLS}} for row in rows]
    return out


def promotions_files(repos: list[Repo], n: int, seed: int, clones: Path | None) -> list[dict]:
    """First-episode promotions of file pairs: file A imported file B only in a deferred way,
    then A itself gained an eager import of B. Step 1 rows = A's imports of B when the pair
    became deferred; step 2 rows = A's eager imports of B at the promoting commit."""
    pool = [(r, e) for r in repos for e in r.episodes("file")
            if e["episode"] == 1 and e["outcome"] == "promoted"]
    picked = sample(pool, n, seed)
    by_repo = defaultdict(list)
    for r, e in picked:
        by_repo[r.name].append((r, e))
    groups = []
    for items in by_repo.values():
        r = items[0][0]
        lines = Lines(clones / r.name if clones else None)
        at = defaultdict(set)
        for _, e in items:
            at[e["start_i"]].add((e["src"], e["dst"]))
            at[e["end_i"]].add((e["src"], e["dst"]))
        found, _ = replay_files(r.con, at)
        for _, e in items:
            s, t, p = e["start_i"], e["end_i"], (e["src"], e["dst"])
            start, dst_path = found.get((s, *p), ([], ""))
            after, _ = found.get((t, *p), ([], ""))
            src_path = start[0][0] if start else ""
            head = {"repo": r.name, "from_file": src_path, "to_file": dst_path}
            rows = line_rows(r, lines, s, "step 1: deferred at start", start)
            rows += line_rows(r, lines, t, "step 2: new eager import",
                              [x for x in after if not is_deferred(x[2])])
            groups.append((head, rows))
    return number(groups)


def cycle_edges_files(repos: list[Repo], n: int, seed: int, clones: Path | None) -> list[dict]:
    """Deferred-only file pairs A -> B at the pinned commit where B can reach A again. Rows:
    A's deferred imports of B, then the imports of each step of the shortest way back."""
    pool = []
    for r in repos:
        eager, dfo = split_pairs(pair_weights(r.con, "file"))
        full = eager | dfo
        for a, b in closing_pairs(sccs(full), dfo):
            pool.append((r, a, b, shortest_path(full, b, a)))
    picked = sample(pool, n, seed)
    by_repo = defaultdict(list)
    for item in picked:
        by_repo[item[0].name].append(item)
    groups = []
    for items in by_repo.values():
        r = items[0][0]
        lines = Lines(clones / r.name if clones else None)
        _, g = replay_files(r.con, {})
        last = max(r.commit)
        for _, a, b, path in items:
            hops = list(pairwise(path))
            head = {"repo": r.name, "from_file": g.path.get(a, ""), "to_file": g.path.get(b, ""),
                    "cycle_length": len(path)}
            rows = line_rows(r, lines, last, "step 1: deferred import", file_links(g, a, b))
            for k, (x, y) in enumerate(hops, 1):
                role = f"way back {k} of {len(hops)}: {g.path.get(x, '')} -> {g.path.get(y, '')}"
                rows += line_rows(r, lines, last, role, file_links(g, x, y))
            groups.append((head, rows))
    return number(groups)


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
    ap.add_argument("--level", choices=["file", "package"], default="file")
    ap.add_argument("--clones", type=Path, default=Path("../clones"),
                    help="folder with one git clone per repo, for line numbers (file level)")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    urls = repo_urls()
    # Fixed repo order, so the same --seed gives the same rows on every machine (a shell glob
    # sorts by locale: Sefaria-Project comes first in C, between relate and saleor in en_US).
    # Case-insensitive, as the en_US glob that made the 19 Nov 2026 lists.
    repos = [Repo(db, urls) for db in sorted(a.dbs, key=lambda p: p.stem.casefold())]
    if a.level == "file":
        p = promotions_files(repos, a.n, a.seed, a.clones)
        c = cycle_edges_files(repos, a.n, a.seed, a.clones)
    else:
        p = promotions(repos, a.n, a.seed)
        c = cycle_edges(repos, a.n, a.seed)
    write(p, a.out / "promotions.csv")
    write(c, a.out / "cycle_edges.csv")
    for name, rows in (("promotions", p), ("cycle-closing edges", c)):
        pairs = len({x["id"] for x in rows})
        missing = sum(x.get("auto_check") == "NOT found" for x in rows)
        print(f"{pairs} {name}, {len(rows)} rows ({a.level} level)"
              + (f", {missing} lines NOT found in the clone" if missing else ""))


if __name__ == "__main__":
    main()
