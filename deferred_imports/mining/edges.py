"""Resolve imports to files, and lift file edges to module edges (tables in schema.sql).

Reads   file_changes, raw_imports, run_info.source_roots and run_info.py2_until
Writes  file_edges, modules, file_modules, module_edges, module_touches, and
        `unresolved` rows in problems

mine.py runs this after the history walk. It can also be run on its own, and it always
rebuilds these tables from scratch, so changing the resolver needs no re-mining:

    uv run python -m deferred_imports.mining.edges index/poetry.sqlite

Resolution. An absolute import `a.b` is looked up as <root>/a/b.py or
<root>/a/b/__init__.py under each source root: the top level, src/, lib/, every directory
with a manage.py, and any listed for the repo in corpus/resolver.csv. Directories without
__init__.py are allowed on the way (PEP 420 namespace packages, as poetry uses). Then:
  - relative imports start at the importer's directory, one level up per extra dot;
  - a file in a plain directory (a script or a test) also sees its own directory;
  - before the date in corpus/resolver.csv's py2_until, a file in a package also sees its
    siblings if nothing else matched: Python 2 implicit relative imports (`import models`),
    never for standard-library names. After it, every importer is resolved again.

A module is a package (a directory with __init__.py). Its name is its path below the source
root, so src/poetry/config and poetry/config are both `poetry.config`, and a move into src/
keeps the module.

Every commit is applied in this order, which decides the `cause` of each edge change:
  1. a deleted file loses its own imports              file edges: delete
  2. paths, packages, modules and module membership    module edges: move, module
  3. importers whose targets appeared or disappeared   file and module edges: resolve
  4. import lines added or removed                     file and module edges: import
  5. deleted files leave their module, module_touches
"""

from __future__ import annotations

import csv
import posixpath
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path

EDGES_VERSION = "2"
RESOLVER_CSV = Path("corpus/resolver.csv")

# Folders we exclude, plus docs_src.
# A package with one of these anywhere in its path is listed in `modules` but gets no edges.
EXCLUDE = {
    "tests": "tests", "test": "tests", "testing": "tests",
    "docs": "docs", "doc": "docs", "docs_src": "docs",
    "examples": "examples", "example": "examples", "samples": "examples", "sample": "examples",
    "migrations": "migrations",
    "vendor": "vendor", "vendored": "vendor", "third_party": "vendor", "_vendor": "vendor",
    "node_modules": "vendor", "site-packages": "vendor",
    "build": "build", "dist": "build",
}
STDLIB = frozenset(sys.stdlib_module_names)


def excluded(dir_path: str) -> str | None:
    for part in dir_path.split("/"):
        if part in EXCLUDE:
            return EXCLUDE[part]
    return None


def source_roots(paths: list[str], extra: list[str] = ()) -> list[str]:
    """The source roots for a repository, from its file paths at the pinned SHA."""
    dirs = {posixpath.dirname(p) for p in paths}
    tops = {p.split("/", 1)[0] for p in paths if "/" in p}
    roots = [""] + [r for r in ("src", "lib") if r in tops]
    roots += sorted(d for d in dirs
                    if d and posixpath.join(d, "manage.py") in paths and excluded(d) is None)
    return list(dict.fromkeys(roots + [r.strip("/") for r in extra]))


def listed(repo_name: str, path: Path = RESOLVER_CSV) -> tuple[list[str], str]:
    """(extra source roots, py2_until date or '') for one repository from corpus/resolver.csv."""
    if path.exists():
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row["name"] == repo_name:
                    return [r for r in row["roots"].split(";") if r], row["py2_until"]
    return [], ""


class Writer:
    """Collects rows for one database. modules and file_modules are written at once, because
    later rows refer to them; the rest is written in batches by flush()."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.rows: dict[str, list] = defaultdict(list)

    def add(self, table: str, row: tuple) -> None:
        self.rows[table].append(row)

    def now(self, sql: str, args: tuple) -> None:
        self.con.execute(sql, args)

    def flush(self) -> None:
        for table, rows in self.rows.items():
            if rows:
                marks = ", ".join("?" * len(rows[0]))
                self.con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
        self.rows.clear()


class Graph:
    """The file graph and module graph at one commit, moved forward one commit at a time.

    With `sink=None` nothing is written; check.py uses that to build the graph at the last
    commit from scratch and compare."""

    def __init__(self, roots: list[str], py2_until: int = -1, sink: Writer | None = None):
        self.roots = list(roots) or [""]
        self.py2_until = py2_until  # last commit with Python 2 implicit relative imports
        self.named_roots = sorted((r for r in self.roots if r), key=len, reverse=True)
        self.sink = sink
        self.i = -1
        # files
        self.path: dict[int, str] = {}                 # file_id -> path, live files only
        self.by_path: dict[str, int] = {}
        self.dir_files: dict[str, set] = defaultdict(set)
        self.dirs: Counter = Counter()                 # directory -> live .py files below it
        self.pkg_dirs: set[str] = set()                # directories with a live __init__.py
        # modules
        self.dir_pkg: dict[str, str] = {}              # package dir -> module name
        self.pkg_dirs_of: dict[str, set] = defaultdict(set)
        self.modules: dict[str, int] = {}              # module name -> open module_id
        self.module_info: dict[int, tuple] = {}        # module_id -> (name, excluded)
        self.mod_of: dict[int, int] = {}               # file_id -> module_id
        self.fm_from: dict[int, int] = {}              # file_id -> from_i of its file_modules row
        self.next_module = 1
        # imports and edges
        self.imports: dict[int, Counter] = defaultdict(Counter)  # (module, name, level, kind)
        self.out: dict[int, Counter] = {}              # file_id -> (dst, kind) -> weight
        self.inc: dict[int, Counter] = defaultdict(Counter)  # dst -> (src, kind) -> weight
        self.keys: dict[int, set] = {}                 # file_id -> lookup keys it depends on
        self.users: dict[str, set] = defaultdict(set)  # lookup key -> file ids
        self.mdelta: Counter = Counter()               # (src_mod, dst_mod, kind, cause) -> net
        self.dangling = 0                              # edges left pointing at a deleted file

    # ------------------------------------------------------------ one commit

    def step(self, i: int, changes: list[tuple], imports: list[tuple]) -> None:
        """changes: (file_id, change, path, old_path); imports: (file_id, delta, stmt, module,
        name, level, kind), sorted by file_id."""
        self.i = i
        deleted = {fid for fid, ch, _, _ in changes if ch == "D" and fid in self.path}
        for fid in sorted(deleted):                                       # 1
            self._set_out(fid, Counter(), "delete")
            self.imports.pop(fid, None)
        flagged = self._update_tree(changes)                              # 2
        if self.py2_until >= 0 and i > self.py2_until:  # Python 3 from here: resolve all again
            flagged |= set(self.out) | set(self.keys)
            self.py2_until = -1
        for fid in sorted(flagged - deleted):                             # 3
            if fid in self.path:
                self._set_out(fid, self._resolve_all(fid), "resolve")
        for fid, rows in groupby(imports, key=itemgetter(0)):             # 4
            if fid not in self.path or fid in deleted:
                continue
            counts = self.imports[fid]
            for _, delta, stmt, module, name, level, kind in rows:
                key = (module, name, level, kind)
                counts[key] += delta
                if counts[key] == 0:
                    del counts[key]
                if (delta > 0 and self.sink
                        and self.resolve(fid, module, name, level)[2] == "unresolved"):
                    self.sink.add("problems", (i, fid, "unresolved", stmt))
            self._set_out(fid, self._resolve_all(fid), "import")
        touched = Counter()                                               # 5
        for fid, _, _, _ in changes:
            m = self.mod_of.get(fid)
            if m is not None and not self.module_info[m][1]:
                touched[m] += 1
        for fid in deleted:
            self._set_module(fid, None, "module")
            self.dangling += sum(self.inc.pop(fid, Counter()).values())
            for k in self.keys.pop(fid, ()):
                self.users[k].discard(fid)
        if self.sink:
            for m, n in sorted(touched.items()):
                self.sink.add("module_touches", (i, m, n))
            for (sm, dm, kind, cause), d in sorted(self.mdelta.items()):
                if d:
                    self.sink.add("module_edges", (i, sm, dm, d, kind, cause))
        self.mdelta.clear()

    def _count_dirs(self, p: str, d: int) -> None:
        if p.endswith(".py"):
            while p:
                p = posixpath.dirname(p)
                if p:
                    self.dirs[p] += d

    def _update_tree(self, changes: list[tuple]) -> set[int]:
        """Apply the path changes of one commit. Returns the importers to re-resolve."""
        removed, added, moved = [], [], set()
        for fid, ch, path, _ in changes:
            if ch == "M" and fid in self.path:
                continue
            if fid in self.path:  # D, R, or (a miner bug) A of a live id
                removed.append((fid, self.path[fid]))
            if ch != "D":
                added.append((fid, path))
                moved.add(fid)
        changed_keys: set[str] = set()
        pkg_changed: set[str] = set()
        for fid, p in removed:
            del self.path[fid], self.by_path[p]
            self.dir_files[posixpath.dirname(p)].discard(fid)
            self._count_dirs(p, -1)
            changed_keys.add("p:" + p)
            if posixpath.basename(p) == "__init__.py":
                pkg_changed.add(posixpath.dirname(p))
        for fid, p in added:
            self.path[fid], self.by_path[p] = p, fid
            self.dir_files[posixpath.dirname(p)].add(fid)
            self._count_dirs(p, 1)
            changed_keys.add("p:" + p)
            if posixpath.basename(p) == "__init__.py":
                pkg_changed.add(posixpath.dirname(p))

        # packages and modules: a module name with at least one package directory is open
        names: set[str] = set()
        for d in sorted(pkg_changed):
            is_pkg = posixpath.join(d, "__init__.py") in self.by_path
            if is_pkg == (d in self.pkg_dirs):
                continue  # removed and added again in the same commit
            changed_keys.add("d:" + d)
            nm = self._module_name(d)
            names.add(nm)
            if is_pkg:
                self.pkg_dirs.add(d)
                self.pkg_dirs_of[nm].add(d)
                self.dir_pkg[d] = nm
            else:
                self.pkg_dirs.discard(d)
                self.pkg_dirs_of[nm].discard(d)
                self.dir_pkg.pop(d, None)
        opened, closed = set(), set()
        for nm in sorted(names):
            dirs = self.pkg_dirs_of.get(nm)
            if dirs and nm not in self.modules:
                mid, self.next_module = self.next_module, self.next_module + 1
                reason = excluded(min(dirs))
                self.modules[nm], self.module_info[mid] = mid, (nm, reason)
                opened.add(mid)
                if self.sink:
                    self.sink.now("INSERT INTO modules VALUES (?, ?, ?, NULL, ?)",
                                  (mid, nm, self.i, reason))
            elif not dirs and nm in self.modules:
                mid = self.modules.pop(nm)
                closed.add(mid)
                if self.sink:
                    self.sink.now("UPDATE modules SET to_i = ? WHERE module_id = ?", (self.i, mid))
            if not dirs:
                self.pkg_dirs_of.pop(nm, None)

        # membership of every file that moved or whose directory changed package
        members = moved | {f for d in pkg_changed for f in self.dir_files.get(d, ())}
        for fid in sorted(f for f in members if f in self.path):
            pkg = self.dir_pkg.get(posixpath.dirname(self.path[fid]))
            new_m = self.modules.get(pkg) if pkg is not None else None  # '' = repository root
            old_m = self.mod_of.get(fid)
            if new_m != old_m:
                cause = "module" if old_m in closed or new_m in opened else "move"
                self._set_module(fid, new_m, cause)

        flagged = set(moved)
        for k in changed_keys:
            flagged |= self.users.get(k, set())
        return flagged

    # ------------------------------------------------------------ resolution

    def _module_name(self, d: str) -> str:
        for r in self.named_roots:
            if d.startswith(r + "/"):
                return d[len(r) + 1:].replace("/", ".")
        return d.replace("/", ".")

    def _roots_for(self, importer: str, stdlib: bool) -> list[str]:
        """Source roots to try, those holding the importer first (longest first). A
        standard-library name is only shadowed by a root the importer itself is in."""
        inside = [r for r in self.named_roots if importer.startswith(r + "/")] + [""]
        return inside if stdlib else inside + [r for r in self.roots if r not in inside]

    def _py(self, p: str) -> int | None:
        fid = self.by_path.get(p)
        return fid if fid is not None and p.endswith(".py") else None

    def resolve(self, fid: int, module: str, name: str | None, level: int, *,
                count: bool = False) -> tuple[int | None, list[str], str]:
        """(target file_id or None, lookup keys read, status). Status is internal, implicit
        (a Python 2 implicit relative import), external, unresolved or self. With count=True
        the status is `ambiguous` when more than one candidate file exists."""
        importer = self.path[fid]
        d = posixpath.dirname(importer)
        sub = name if name and name != "*" else None
        keys: list[str] = []
        found: list[int] = []

        def paths(base: str, mod: str) -> list[str]:
            stem = posixpath.join(base, *mod.split(".")) if mod else base
            out = [posixpath.join(stem, sub + ".py"), posixpath.join(stem, sub, "__init__.py")] \
                if sub else []
            out += [stem + ".py", posixpath.join(stem, "__init__.py")] if mod else \
                [posixpath.join(base, "__init__.py")]
            return out

        def first(cands: list[str]) -> int | None:
            for p in cands:
                keys.append("p:" + p)
                f = self._py(p)
                if f is not None:
                    return f
            return None

        if level:  # relative: start at the importer's directory, one level up per extra dot
            base = d
            for _ in range(level - 1):
                if not base:
                    return None, keys, "unresolved"
                base = posixpath.dirname(base)
            dst = first(paths(base, module))
            status = "internal" if dst is not None else "unresolved"
            return dst, keys, "self" if dst == fid else status

        top = module.split(".", 1)[0]
        stdlib = top in STDLIB
        dst, status = None, "internal"
        for r in self._roots_for(importer, stdlib):
            f = first(paths(r, module))
            if f is not None:
                found.append(f)
                if not count:
                    break
        keys.append("d:" + d)
        in_package = d in self.pkg_dirs
        if in_package:  # Python 2 implicit relative import
            sibling = not stdlib and self.i <= self.py2_until
        else:  # a script or test sees its own directory, unless it is a namespace under src/
            sibling = not any(importer.startswith(r + "/") for r in self.named_roots)
        if sibling and (count or not found):
            f = first(paths(d, module))
            if f is not None and f not in found:
                if not found:
                    status = "implicit" if in_package else "internal"
                found.append(f)
        if found:
            dst = found[0]
            if count and len(set(found)) > 1:
                status = "ambiguous"
        else:
            status = self._classify(importer, module, stdlib, d if sibling else None)
        return dst, keys, "self" if dst == fid else status

    def _classify(self, importer: str, module: str, stdlib: bool, own_dir: str | None) -> str:
        """`unresolved` if the import names code that should be in the repository: the deepest
        part of its name that exists is a module or a regular package. A name that only
        reaches a namespace directory (poetry.core under poetry's src/poetry) is `external`."""
        for r in self._roots_for(importer, stdlib) + ([own_dir] if own_dir is not None else []):
            cur, last = r, None
            for part in module.split("."):
                cur = posixpath.join(cur, part)
                if cur + ".py" in self.by_path or cur in self.pkg_dirs:
                    last = "regular"
                elif self.dirs[cur]:
                    last = "namespace"
                else:
                    break
            if last == "regular":
                return "unresolved"
        return "external"

    def _resolve_all(self, fid: int) -> Counter:
        res: Counter = Counter()
        keys: set[str] = set()
        for (module, name, level, kind), n in self.imports.get(fid, Counter()).items():
            if n <= 0:
                continue
            dst, ks, _ = self.resolve(fid, module, name, level)
            keys.update(ks)
            if dst is not None and dst != fid:
                res[(dst, kind)] += n
        old = self.keys.get(fid, set())
        for k in old - keys:
            self.users[k].discard(fid)
        for k in keys - old:
            self.users[k].add(fid)
        self.keys[fid] = keys
        return res

    # ------------------------------------------------------------ edges

    def _lift(self, sm, dm, kind: str, w: int, cause: str) -> None:
        if sm is None or dm is None or sm == dm:
            return  # outside any package, or inside one module
        if self.module_info[sm][1] or self.module_info[dm][1]:
            return  # tests, docs, vendored code ...
        self.mdelta[(sm, dm, kind, cause)] += w

    def _set_out(self, fid: int, new: Counter, cause: str) -> None:
        old = self.out.get(fid, Counter())
        if old == new:
            return
        mcause = "resolve" if cause == "resolve" else "import"
        sm = self.mod_of.get(fid)
        for key in sorted(set(old) | set(new)):
            d = new.get(key, 0) - old.get(key, 0)
            if not d:
                continue
            dst, kind = key
            if self.sink:
                row = (self.i, fid, dst, 1 if d > 0 else -1, kind, cause)
                for _ in range(abs(d)):
                    self.sink.add("file_edges", row)
            inc = self.inc[dst]
            inc[(fid, kind)] += d
            if inc[(fid, kind)] == 0:
                del inc[(fid, kind)]
            self._lift(sm, self.mod_of.get(dst), kind, d, mcause)
        if new:
            self.out[fid] = new
        else:
            self.out.pop(fid, None)

    def _set_module(self, fid: int, new_m, cause: str) -> None:
        old_m = self.mod_of.get(fid)
        if old_m == new_m:
            return
        for sign, m in ((-1, old_m), (1, new_m)):
            for (dst, kind), w in self.out.get(fid, Counter()).items():
                self._lift(m, self.mod_of.get(dst), kind, sign * w, cause)
            for (src, kind), w in self.inc.get(fid, Counter()).items():
                self._lift(self.mod_of.get(src), m, kind, sign * w, cause)
            if sign < 0:
                if new_m is None:
                    self.mod_of.pop(fid, None)
                else:
                    self.mod_of[fid] = new_m
        if self.sink:
            start = self.fm_from.pop(fid, None)
            if start == self.i:  # the row opened in this commit: replace it
                self.sink.now("DELETE FROM file_modules WHERE file_id = ? AND from_i = ?",
                              (fid, start))
            elif start is not None:
                self.sink.now("UPDATE file_modules SET to_i = ? WHERE file_id = ? AND from_i = ?",
                              (self.i, fid, start))
            if new_m is not None:
                self.sink.now("INSERT INTO file_modules VALUES (?, ?, ?, NULL)",
                              (fid, new_m, self.i))
                self.fm_from[fid] = self.i

    # ------------------------------------------------------------ summaries

    def file_weights(self) -> Counter:
        return Counter({(s, d, k): w for s, out in self.out.items() for (d, k), w in out.items()})

    def module_weights(self) -> Counter:
        """(src module name, dst module name, kind) -> weight, as lifting counts it."""
        out: Counter = Counter()
        for (s, d, k), w in self.file_weights().items():
            sm, dm = self.mod_of.get(s), self.mod_of.get(d)
            if sm is None or dm is None or sm == dm:
                continue
            if self.module_info[sm][1] or self.module_info[dm][1]:
                continue
            out[(self.module_info[sm][0], self.module_info[dm][0], k)] += w
        return out

    def stats(self) -> dict:
        status: Counter = Counter()
        for fid, imps in self.imports.items():
            if fid not in self.path:
                continue
            for (module, name, level, kind), n in imps.items():
                if n > 0:
                    status[self.resolve(fid, module, name, level, count=True)[2]] += n
        mods = [m for m in self.modules.values() if not self.module_info[m][1]]
        return {
            "n_internal_imports": status["internal"] + status["implicit"] + status["ambiguous"],
            "n_implicit_relative": status["implicit"],
            "n_ambiguous_imports": status["ambiguous"],
            "n_external_imports": status["external"],
            "n_unresolved_imports": status["unresolved"],
            "n_self_imports": status["self"],
            "n_file_edges": sum(self.file_weights().values()),
            "n_modules": len(mods),
            "n_modules_excluded": len(self.modules) - len(mods),
            "n_module_pairs": len({(s, d) for s, d, _ in self.module_weights()}),
            "n_dangling_edges": self.dangling,
        }


def _by_commit(ro: sqlite3.Connection):
    """Yield (i, changes, imports) in commit order."""
    ch = groupby(ro.execute("SELECT i, file_id, change, path, old_path FROM file_changes "
                            "ORDER BY i, file_id"), key=itemgetter(0))
    im = groupby(ro.execute("SELECT i, file_id, delta, stmt, module, name, level, kind "
                            "FROM raw_imports ORDER BY i, file_id, rowid"), key=itemgetter(0))
    a, b = next(ch, None), next(im, None)
    while a or b:
        i = min(x[0] for x in (a, b) if x)
        changes, imports = [], []
        if a and a[0] == i:
            changes = [r[1:] for r in a[1]]
            a = next(ch, None)
        if b and b[0] == i:
            imports = [r[1:] for r in b[1]]
            b = next(im, None)
        yield i, changes, imports


def settings_of(con: sqlite3.Connection) -> tuple[list[str], int]:
    """(source roots, last commit index before py2_until, or -1) from run_info."""
    info = dict(con.execute("SELECT key, value FROM run_info "
                            "WHERE key IN ('source_roots', 'py2_until')"))
    until = -1
    if info.get("py2_until"):
        row = con.execute("SELECT MAX(i) FROM commits WHERE date < ?", (info["py2_until"],))
        until = row.fetchone()[0]
        until = -1 if until is None else until
    return info.get("source_roots", "").split(";"), until


def build(con: sqlite3.Connection, batch: int = 1000) -> dict:
    """Rebuild every edge table from file_changes and raw_imports; return the run_info stats."""
    t0 = time.time()
    # churn.py's tables point at modules, and new module ids make them stale: rerun churn.py
    con.execute("DROP TABLE IF EXISTS module_churn")
    con.execute("DROP TABLE IF EXISTS commit_churn")
    for table in ("module_touches", "module_edges", "file_modules", "file_edges", "modules"):
        con.execute(f"DELETE FROM {table}")
    con.execute("DELETE FROM problems WHERE kind = 'unresolved'")
    db = con.execute("PRAGMA database_list").fetchone()[2]
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sink = Writer(con)
    g = Graph(*settings_of(con), sink=sink)
    for n, (i, changes, imports) in enumerate(_by_commit(ro), 1):
        g.step(i, changes, imports)
        if n % batch == 0:
            sink.flush()
    sink.flush()
    ro.close()
    stats = g.stats()
    stats["edges_version"] = EDGES_VERSION
    stats["edges_seconds"] = f"{time.time() - t0:.0f}"
    con.executemany("INSERT OR REPLACE INTO run_info VALUES (?, ?)",
                    [(k, str(v)) for k, v in stats.items()])
    con.commit()
    return stats


def main(argv=None) -> int:
    from deferred_imports.mining import schema

    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 2
    con = schema.connect(Path(argv[0]))
    stats = build(con)
    con.close()
    print(", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
