"""R3 hand-check lists: random samples of promotions (E2) and of deferred-only edges that close a
cycle (E3), written so a person can check each row on GitHub.

    uv run python -m deferred_imports.analysis.handcheck index/*.sqlite --out handcheck [--n 60]
        [--level file|package] [--clones ../clones]

--level file (the default, the level of the paper's results) writes one row per import line:
each pair gets an id, and its rows are the exact import lines our miner counted, with the file,
the line number, the commit and a GitHub link that opens that line. A checker writes yes/no per
line. The line number is found by reading the file at that commit from the local clone
(--clones) with the miner's own parser; `auto_check` says whether the line was found there.
--level package writes the package-level lists described below.

Writes two CSV files (they open in Excel or Google Sheets):

  promotions.csv   first-episode promotions: package A -> B was linked only by deferred imports,
                   then gained an eager import. Columns: the two packages, the commit where the
                   pair became deferred and the commit where it was promoted (SHA, date, GitHub
                   link), lifetimes, the import lines linking A to B after each of the two
                   commits, and the new eager import lines that make it a promotion.
  cycle_edges.csv  deferred-only pairs A -> B at the pinned commit where B can reach A again, so
                   the deferred import closes a cycle. Columns: the deferred import lines, the
                   shortest way back B -> ... -> A with the import lines of each step, and the
                   commit where the pair became deferred with its import lines then.

Each file ends with empty columns for the checkers. Next to each, <name>_lines.csv has one row per
import line of every case: its step (role), whether it is `deferred` or `normal` (runs when the
file loads) and where it sits in plain words, the file, line and commit, a GitHub link in its own
cell, an automatic second opinion from Python's own ast (`agrees`, `DIFFERS`, or `python 2 (not
checked)`), and empty columns to mark each line. --n 0 writes every case instead of a sample. What to decide for each row:
  promotions   ok = yes if, at the start commit, A uses B only inside functions or under
               TYPE_CHECKING, and the promoting commit adds an import of B that runs when A loads.
  cycle edges  ok = yes if A really imports B only in a deferred way at the pinned commit, and
               every step of the way back is a real import.

With --level package both lists are at the package level (module pairs), as in the research plan.
At either level the samples are drawn from all given repositories pooled, with a fixed --seed, so the same command gives the same rows.
The import lines are found by replaying the edge build (edges.Graph), so they are exactly the
imports the miner counted. With the clones at hand (--clones, default ../clones), every import line
also gets a GitHub link to that line in that file at that commit (the *_evidence columns).
"""

from __future__ import annotations

import argparse
import ast
import csv
import random
import re
import sqlite3
import subprocess
import warnings
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from urllib.parse import quote

from deferred_imports.analysis.cycles import closing_pairs, sccs, shortest_path
from deferred_imports.analysis.fate import episodes
from deferred_imports.analysis.graphs import is_deferred, pair_weights, split_pairs
from deferred_imports.mining.edges import Graph, _by_commit, settings_of
from deferred_imports.mining.mine import import_lines
from deferred_imports.mining.verify import never_runs

WHERE = {"in_function": "inside a function", "type_checking": "under if TYPE_CHECKING (never runs)",
         "try_except": "inside try/except (still runs at load)", "top_level": "top of the file"}
LINE_CHECK = ["checker_a (ok?)", "checker_b (ok?)", "line_note"]  # package level *_lines.csv
LINE_COLS = ["ok (yes/no)", "note"]  # file level

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


def links(g: Graph, sm: int, dm: int) -> list[tuple]:
    """The imports that link package sm to package dm in g's current state, as
    (path, module, name, level, kind), one per import."""
    out = []
    for fid, m in list(g.mod_of.items()):
        if m != sm or fid not in g.path:
            continue
        for (module, name, level, kind), n in g.imports.get(fid, {}).items():
            if n <= 0:
                continue
            dst = g.resolve(fid, module, name, level)[0]
            if dst is not None and dst != fid and g.mod_of.get(dst) == dm:
                out += [(g.path[fid], module, name, level, kind)] * n
    return sorted(out, key=str)


def copies(items: list[tuple]) -> list[tuple[tuple, int]]:
    """Each item with how many identical items came before it (the same import, twice)."""
    seen: Counter = Counter()
    out = []
    for x in items:
        out.append((x, seen[x]))
        seen[x] += 1
    return out


def more(items: list, lines: list[str]) -> str:
    extra = len(items) - MAX_LINES
    return "\n".join(lines + ([f"... and {extra} more"] if extra > 0 else []))


def show(items: list[tuple]) -> str:
    return more(items, [f"{path}: {stmt_text(mod, name, lvl)}  [{kind}]"
                        for path, mod, name, lvl, kind in items[:MAX_LINES]])


def statement(lines: list[str], k: int) -> str:
    """The whole import statement starting at line k: up to the closing ')' of a
    parenthesized list, or over backslash continuations."""
    text = lines[k]
    if "(" in text.split("import", 1)[-1]:
        j = k
        while ")" not in lines[j] and j + 1 < len(lines):
            j += 1
            text += "\n" + lines[j]
        return text.split(")")[0]
    j = k
    while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
        j += 1
        text += "\n" + lines[j]
    return text


def where(kind: str) -> str:
    """The kind in plain words: "inside a function + inside try/except"."""
    tags = kind.split("+")
    if "try_except" in tags and len(tags) > 1:  # inside a function too: it does not run at load
        return " + ".join(WHERE.get(t, t) if t != "try_except" else "inside try/except"
                          for t in tags)
    return " + ".join(WHERE.get(t, t) for t in tags)


def ast_imports(src: bytes) -> dict[int, list[tuple[str, str]]] | None:
    """{line: [(import, kind)]} from Python's own ast, with the context tagged by verify.py's
    rule, so it shares no code with the tree-sitter miner. None if Python 3 cannot parse it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None
    out: dict = {}

    def walk(node, tags):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.Import, ast.ImportFrom)):
                if isinstance(ch, ast.ImportFrom) and ch.level == 0 and ch.module == "__future__":
                    continue
                kind = "+".join(t for t in WHERE if t in tags) or "top_level"
                for a in ch.names:
                    text = f"import {a.name}" if isinstance(ch, ast.Import) else \
                        f"from {'.' * ch.level}{ch.module or ''} import {a.name}"
                    out.setdefault(ch.lineno, []).append((text, kind))
                continue
            if (isinstance(ch, ast.If) and len(ch.orelse) == 1 and isinstance(ch.orelse[0], ast.If)
                    and ch.orelse[0].col_offset == ch.col_offset):
                ch.orelse[0].is_elif = True  # the miner reads TYPE_CHECKING in `if` only
            t = tags
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                t = t | {"in_function"}
            elif isinstance(ch, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                t = t | {"try_except"}
            elif (isinstance(ch, ast.If) and not getattr(ch, "is_elif", False)
                  and (side := never_runs(ast.unparse(ch.test)))):
                for b in ch.body:
                    walk(ast.Module(body=[b], type_ignores=[]),
                         t | {"type_checking"} if side == "body" else t)
                for b in ch.orelse:
                    walk(ast.Module(body=[b], type_ignores=[]),
                         t | {"type_checking"} if side == "else" else t)
                continue
            walk(ch, t)

    walk(tree, frozenset())
    return out


def find_line(text: str, module: str, name: str | None, level: int, kind: str,
              nth: int = 0) -> int | None:
    """1-based line of an import in a file, or None. A deferred import prefers an indented
    line, a top-level one an unindented line; `from a import (b, c)` may span lines.
    nth = 1 for the second time the same import appears in the file (two functions that
    each import it), and so on."""
    lines = text.splitlines()
    if name is None:
        rx = re.compile(r"^\s*import\s.*(?<![\w.])" + re.escape(module) + r"(?![\w.])")
    else:
        rx = re.compile(r"^\s*from\s+" + re.escape("." * level + module) + r"\s+import\b")
    word = re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w.])") if name and name != "*" \
        else None
    hits = []
    for k, line in enumerate(lines):
        if not rx.search(line):
            continue
        if word and not word.search(statement(lines, k)):
            continue
        hits.append(k)
    if not hits:
        return None
    indented = kind != "top_level"
    best = [k for k in hits if (lines[k][:1] in " \t") == indented] or hits
    return best[min(nth, len(best) - 1)] + 1


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
    def __init__(self, db: Path, urls: dict[str, str], clones: Path | None = None):
        self.db, self.name = db, db.stem
        clone = clones / self.name if clones else None
        self.clone = clone if clone is not None and (clone / ".git").exists() else None
        self._files: dict = {}
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

    def file_at(self, sha: str, path: str) -> tuple[str, dict, dict | None] | None:
        """(text, import_lines by tree-sitter, imports by Python's ast or None) of a file at a
        commit, from the local clone; None without a clone."""
        if self.clone is None:
            return None
        if (sha, path) not in self._files:
            r = subprocess.run(["git", "-C", str(self.clone), "show", f"{sha}:{path}"],
                               check=False, capture_output=True)
            self._files[(sha, path)] = ((r.stdout.decode("utf-8", "replace"),
                                         import_lines(r.stdout), ast_imports(r.stdout))
                                        if r.returncode == 0 else None)
        return self._files[(sha, path)]

    def ast_check(self, sha: str, item: tuple, line: int | None) -> str:
        """Python's ast, independent of the miner: does this line hold this import, this kind?"""
        got = self.file_at(sha, item[0])
        if got is None or line is None:
            return "not checked (no clone)"
        if got[2] is None:
            return "python 2 (not checked)"
        _, mod, name, lvl, kind = item
        return "agrees" if (stmt_text(mod, name, lvl), kind) in got[2].get(line, []) \
            else "DIFFERS"

    def locate(self, sha: str, item: tuple, nth: int = 0) -> tuple[int | None, str]:
        """(line number or None, GitHub link to the file at sha, to that line when found).
        nth: this is the nth copy of the same import in the list (0 = the first)."""
        path, mod, name, lvl, kind = item
        n, got = None, self.file_at(sha, path)
        if got is not None:
            # the miner's own parse: the exact statement with this text and kind
            lines = got[1].get((stmt_text(mod, name, lvl), kind))
            n = lines[min(nth, len(lines) - 1)] if lines else \
                find_line(got[0], mod, name, lvl, kind, nth)
        url = f"{self.url}/blob/{sha}/{quote(path)}" + (f"#L{n}" if n else "") if self.url else ""
        return n, url

    def evidence(self, sha: str, items: list[tuple]) -> str:
        """A GitHub link per import line shown by show(), to the line itself when found."""
        if not self.url:
            return ""
        return more(items, [self.locate(sha, x, k)[1] for x, k in copies(items[:MAX_LINES])])

    def line_rows(self, role: str, sha: str, items: list[tuple]) -> list[dict]:
        """One row per import for the *_lines.csv file: every import, one link per cell."""
        out = []
        for item, k in copies(items):
            n, url = self.locate(sha, item, k)
            path, mod, name, lvl, kind = item
            out.append({"role": role,
                        "type": "deferred" if is_deferred(kind) else "normal",
                        "where": where(kind), "import": stmt_text(mod, name, lvl),
                        "file": path, "line": n or "", "commit": sha[:10], "link": url,
                        "ast_check": self.ast_check(sha, item, n), "kind": kind})
        return out


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
            at_s, at_t = found.get((s, *p), []), found.get((t, *p), [])
            # the proof of a promotion: eager imports of B that A has after it and not before
            new = Counter(x for x in at_t if not is_deferred(x[4])) \
                - Counter(x for x in at_s if not is_deferred(x[4]))
            new_eager = sorted(new.elements(), key=str)
            rows.append({
                "repo": r.name,
                "from_package": r.name_of(e["src"]), "to_package": r.name_of(e["dst"]),
                "deferred_since": f"{r.sha(s)} ({r.commit[s][1]})",
                "promoted_at": f"{r.sha(t)} ({r.commit[t][1]})",
                "commits": e["commits"], "active_commits": e["active_commits"],
                "days": e["days"], "hoisted": e["hoisted"], "type_only": int(e["type_only"]),
                "from_state": e["from_state"],
                "imports_at_start": show(at_s),
                "start_evidence": r.evidence(r.commit[s][0], at_s),
                "new_eager_imports": show(new_eager),
                "new_eager_evidence": r.evidence(r.commit[t][0], new_eager),
                "imports_after_promotion": show(at_t),
                "promotion_evidence": r.evidence(r.commit[t][0], at_t),
                "start_commit_url": r.link(s), "promotion_commit_url": r.link(t),
                "_lines": r.line_rows("step 1: deferred at start", r.commit[s][0], at_s)
                + r.line_rows("step 2: new eager import", r.commit[t][0], new_eager),
            })
    return finish(rows, ["checker_a (yes/no)", "checker_b (yes/no)", "final (yes/no)", "note"])


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
        since = {(e["src"], e["dst"]): e["start_i"] for e in r.episodes()
                 if e["outcome"] == "kept"}
        at = defaultdict(set)
        for _, a, b, _, _ in items:
            if (a, b) in since:
                at[since[(a, b)]].add((a, b))
        found, g = replay(r.con, at)
        last = max(r.commit)
        for _, a, b, path, eager in items:
            hops = list(pairwise(path))
            back, back_urls, back_lines = [], [], []
            for x, y in hops:
                kind = "eager" if (x, y) in eager else "deferred"
                hop = links(g, x, y)
                back.append(f"{r.name_of(x)} -> {r.name_of(y)} ({kind}):")
                back += ["    " + line for line in show(hop).split("\n")]
                back_urls.append(f"{r.name_of(x)} -> {r.name_of(y)}:")
                back_urls += ["    " + u for u in r.evidence(r.pinned, hop).split("\n")]
                back_lines += r.line_rows(f"step 2: way back {r.name_of(x)} -> {r.name_of(y)} ({kind})",
                                          r.pinned, hop)
            dfo_items = links(g, a, b)
            s = since.get((a, b))
            at_s = found.get((s, a, b), []) if s is not None else []
            rows.append({
                "repo": r.name,
                "from_package": r.name_of(a), "to_package": r.name_of(b),
                "deferred_imports": show(dfo_items),
                "deferred_evidence": r.evidence(r.pinned, dfo_items),
                "cycle": " -> ".join(r.name_of(x) for x in [a, *path]),
                "cycle_length": len(path),
                "way_back_all_eager": int(all((x, y) in eager for x, y in hops)),
                "way_back_imports": "\n".join(back),
                "way_back_evidence": "\n".join(back_urls),
                "deferred_since": f"{r.sha(s)} ({r.commit[s][1]})" if s is not None else "",
                "deferred_since_imports": show(at_s),
                "deferred_since_evidence": r.evidence(r.commit[s][0], at_s) if s is not None
                else "",
                "deferred_since_url": r.link(s) if s is not None else "",
                "pinned_tree_url": f"{r.url}/tree/{r.pinned}" if r.url else "",
                "last_commit": r.sha(last),
                "_lines": r.line_rows("step 1: deferred import", r.pinned, dfo_items) + back_lines
                + (r.line_rows("step 3: deferred since", r.commit[s][0], at_s) if s is not None else []),
            })
    return finish(rows, ["checker_a (yes/no)", "checker_b (yes/no)", "final (yes/no)", "note"])


# ---------------------------------------------------------------- file level (the paper's level)

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


def file_line_rows(r: Repo, lines: Lines, i: int, role: str,
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
            rows = file_line_rows(r, lines, s, "step 1: deferred at start", start)
            rows += file_line_rows(r, lines, t, "step 2: new eager import",
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
            rows = file_line_rows(r, lines, last, "step 1: deferred import", file_links(g, a, b))
            for k, (x, y) in enumerate(hops, 1):
                role = f"way back {k} of {len(hops)}: {g.path.get(x, '')} -> {g.path.get(y, '')}"
                rows += file_line_rows(r, lines, last, role, file_links(g, x, y))
            groups.append((head, rows))
    return number(groups)


def finish(rows: list[dict], blank: list[str]) -> list[dict]:
    rows.sort(key=lambda x: (x["repo"], x["from_package"], x["to_package"]))
    return [{"id": k, **row, **{c: "" for c in blank}} for k, row in enumerate(rows, 1)]


def write(rows: list[dict], path: Path) -> None:
    """The list itself, and next to it <name>_lines.csv: one row per import line of each case,
    with its own link, so every link is one click and nothing is cut at MAX_LINES."""
    with open(path, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != "_lines"])
            w.writeheader()
            w.writerows({k: v for k, v in row.items() if k != "_lines"} for row in rows)
    if not any("_lines" in row for row in rows):  # file level: the list is already per line
        return
    lines = [{"id": row["id"], "repo": row["repo"], "from_package": row["from_package"],
              "to_package": row["to_package"], **x, **{c: "" for c in LINE_CHECK}}
             for row in rows for x in row["_lines"]]
    with open(path.with_name(path.stem + "_lines.csv"), "w", newline="") as f:
        if lines:
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("handcheck"))
    ap.add_argument("--n", type=int, default=60, help="rows per list; 0 = all (default 60)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--level", choices=["file", "package"], default="file")
    ap.add_argument("--clones", type=Path, default=Path("../clones"),
                    help="folder with one git clone per repo, for line numbers and links")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    urls = repo_urls()
    # Fixed repo order, so the same --seed gives the same rows on every machine (a shell glob
    # sorts by locale: Sefaria-Project comes first in C, between relate and saleor in en_US).
    # Case-insensitive, as the en_US glob that made the 19 Nov 2026 lists.
    repos = [Repo(db, urls, a.clones) for db in sorted(a.dbs, key=lambda p: p.stem.casefold())]
    if a.level == "file":
        p = promotions_files(repos, a.n, a.seed, a.clones)
        c = cycle_edges_files(repos, a.n, a.seed, a.clones)
    else:
        p = promotions(repos, a.n, a.seed)
        c = cycle_edges(repos, a.n, a.seed)
    write(p, a.out / "promotions.csv")
    write(c, a.out / "cycle_edges.csv")
    if a.level == "package":
        print(f"{len(p)} promotions -> {a.out / 'promotions.csv'} (+ promotions_lines.csv)")
        print(f"{len(c)} cycle-closing edges -> {a.out / 'cycle_edges.csv'} "
              "(+ cycle_edges_lines.csv)")
        for name, rows in (("promotions_lines", p), ("cycle_edges_lines", c)):
            lines = [x for row in rows for x in row["_lines"]]
            types, checks = Counter(x["type"] for x in lines), Counter(x["ast_check"] for x in lines)
            print(f"  {name}.csv: {len(lines)} import lines, {types['deferred']} deferred, "
                  f"{types['normal']} normal; ast check: "
                  + ", ".join(f"{v} {k}" for k, v in checks.most_common()))
        return
    for name, rows in (("promotions", p), ("cycle-closing edges", c)):
        pairs = len({x["id"] for x in rows})
        missing = sum(x.get("auto_check") == "NOT found" for x in rows)
        print(f"{pairs} {name}, {len(rows)} rows (file level)"
              + (f", {missing} lines NOT found in the clone" if missing else ""))


if __name__ == "__main__":
    main()
