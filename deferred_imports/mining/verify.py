"""Check a mined event log against git, without using any other deferred_imports code.

    uv run python -m deferred_imports.mining.verify <clone> index/<repo>.sqlite [--out report.json] [--checkpoints 25]
    uv run python -m deferred_imports.mining.verify <clone> index/<repo>.sqlite

docs/data-check.md explains the checks and the results on the corpus.

Everything is recomputed from git (`git log --first-parent`, `git diff-tree -M --raw --numstat`
against the first parent, `git ls-tree`, the blobs) and Python's `ast`, then compared with
the tables. The miner uses tree-sitter and edges.py works one commit at a time; this script
uses `ast` and rebuilds the graph from the whole tree, so a bug in either one shows up.

Per commit (every commit):
  commits       sha order, committer date, number of parents, number of changed files
  file_changes  change type, path, old path, lines added and deleted, loc_after
  raw_imports   the imports added and removed in each changed .py file (ast on both blobs)
  module_touches  changed files per module
  commit_churn  .py files and lines per commit, is_large
At checkpoints (evenly spaced commits and the last one):
  file_paths    the open paths are exactly the files git lists
  modules       the open modules are exactly the packages in the tree
  file_modules  every file's module
  file_edges    the summed file graph equals the graph resolved from scratch
  module_edges  the summed module graph equals the lifted graph
Per window (every month and 90-day window):
  module_churn  commits, lines and their merge/format/large/agent parts, loc_end, relative

Files that Python 3's `ast` cannot parse (Python 2 code) are counted and skipped in the
raw_imports check; at checkpoints their imports are taken from raw_imports instead.
"""

import argparse
import ast
import json
import posixpath
import sqlite3
import subprocess
import sys
import time
import warnings
from collections import Counter, defaultdict
from datetime import date


def never_runs(cond: str) -> str | None:
    """Which part of `if <cond>:` never runs at runtime (kept separate from mine.py on purpose).
    "body" for TYPE_CHECKING / x.TYPE_CHECKING / False, "else" for `not` of those, else None.
    Other conditions that mention TYPE_CHECKING without `not` count as "body" (old rule)."""
    c = " ".join(cond.split())
    while c.startswith("(") and c.endswith(")") and c.count("(") == 1:
        c = c[1:-1].strip()
    neg = c.startswith("not ")
    if neg:
        c = c[4:].strip()
        while c.startswith("(") and c.endswith(")") and c.count("(") == 1:
            c = c[1:-1].strip()
    simple = c == "False" or (c.split(".")[-1] == "TYPE_CHECKING"
                              and all(p.isidentifier() for p in c.split(".")))
    if simple:
        return "else" if neg else "body"
    if not neg and "TYPE_CHECKING" in c and "not" not in c.split():
        return "body"
    return None

EXCLUDE = {"tests", "test", "testing", "docs", "doc", "docs_src", "examples", "example",
           "samples", "sample", "migrations", "vendor", "vendored", "third_party", "_vendor",
           "node_modules", "site-packages", "build", "dist"}
STDLIB = frozenset(sys.stdlib_module_names)
LARGE_FILES, LARGE_LINES, WINDOW_DAYS = 100, 10_000, 90
PY_MODES = ("100644", "100755")
warnings.simplefilter("ignore")


class Check:
    """Counts of compared items and mismatches per check, with a few examples."""

    def __init__(self):
        self.n, self.bad, self.ex = Counter(), Counter(), defaultdict(list)

    def eq(self, name, a, b, where=None):
        self.n[name] += 1
        if a != b:
            self.bad[name] += 1
            if len(self.ex[name]) < 10:
                show = lambda x: {str(k): v for k, v in x.items()} if isinstance(x, dict) else x
                self.ex[name].append({"where": where, "db": show(a), "git": show(b)})
            return False
        return True

    def sets(self, name, db: dict, truth: dict, where=None):
        """Compare two {key: value} maps item by item."""
        for k in db.keys() | truth.keys():
            self.eq(name, db.get(k), truth.get(k), [where, k])


def run(args):
    t0 = time.time()
    clone, db = args.clone, args.db
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    git = lambda *a: subprocess.run(["git", "-C", clone, "-c", "core.quotepath=off", *a],
                                    capture_output=True, check=True).stdout
    info = dict(q("SELECT key, value FROM run_info"))
    roots = info["source_roots"].split(";")
    named_roots = sorted((r for r in roots if r), key=len, reverse=True)
    C = Check()

    # ---------------------------------------------------------------- blobs
    cat = subprocess.Popen(["git", "-C", clone, "cat-file", "--batch"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    blob_cache: dict = {}

    def blob(sha):
        cat.stdin.write(sha.encode() + b"\n")
        cat.stdin.flush()
        hdr = cat.stdout.readline().split()
        data = cat.stdout.read(int(hdr[2]))
        cat.stdout.read(1)
        return data

    def loc(data):
        return data.count(b"\n") + (bool(data) and not data.endswith(b"\n"))

    def imports_of(sha):
        """Counter of (stmt, kind) by ast, or None if ast cannot parse it. Cached by blob."""
        if sha in blob_cache:
            return blob_cache[sha]
        data = blob(sha)
        try:
            tree = ast.parse(data)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            res = None
        else:
            res = Counter()

            def walk(node, tags):
                for ch in ast.iter_child_nodes(node):
                    t = tags
                    if isinstance(ch, ast.Import):
                        for a in ch.names:
                            res[(f"import {a.name}", kind(t))] += 1
                        continue
                    if isinstance(ch, ast.ImportFrom):
                        mod = "." * ch.level + (ch.module or "")
                        if ch.level == 0 and ch.module == "__future__":
                            continue
                        for a in ch.names:
                            res[(f"from {mod} import {a.name}", kind(t))] += 1
                        continue
                    if (isinstance(ch, ast.If) and len(ch.orelse) == 1
                            and isinstance(ch.orelse[0], ast.If)
                            and ch.orelse[0].col_offset == ch.col_offset):
                        ch.orelse[0].is_elif = True  # the miner reads TYPE_CHECKING in `if` only
                    if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        t = t | {"in_function"}
                    elif isinstance(ch, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                        t = t | {"try_except"}
                    elif (isinstance(ch, ast.If) and not getattr(ch, "is_elif", False)
                          and (side := never_runs(ast.unparse(ch.test)))):
                        # `if TYPE_CHECKING:` / `if False:` -> body never runs;
                        # `if not TYPE_CHECKING:` -> body runs, else/elif part never runs
                        tb = t | {"type_checking"}
                        for b in ch.body:
                            walk_one(b, tb if side == "body" else t)
                        for b in ch.orelse:
                            walk_one(b, tb if side == "else" else t)
                        continue
                    walk(ch, t)

            def walk_one(node, tags):
                holder = ast.Module(body=[node], type_ignores=[])
                walk(holder, tags)

            walk(tree, frozenset())
        if len(blob_cache) > 200_000:
            blob_cache.clear()
        blob_cache[sha] = res
        return res

    def kind(tags):
        order = ["in_function", "type_checking", "try_except"]
        return "+".join(x for x in order if x in tags) or "top_level"

    # ---------------------------------------------------------------- trees
    def tree(sha):
        out = {}
        for ent in git("ls-tree", "-r", "-z", sha).split(b"\0"):
            if ent:
                meta, path = ent.split(b"\t", 1)
                mode, _, obj = meta.decode().split()
                out[path.decode("utf-8", "replace")] = (mode, obj)
        return out

    def pkgs(t):
        return {posixpath.dirname(p) for p in t if posixpath.basename(p) == "__init__.py"}

    def modname(d):
        for r in named_roots:
            if d.startswith(r + "/"):
                return d[len(r) + 1:].replace("/", ".")
        return d.replace("/", ".")

    def is_excl(d):
        return any(p in EXCLUDE for p in d.split("/"))

    mods = q("SELECT module_id, name, from_i, to_i, excluded FROM modules")
    by_name = defaultdict(list)
    for mid, nm, f, t, ex in mods:
        by_name[nm].append((f, t, mid))
    mod_name = {mid: nm for mid, nm, *_ in mods}
    mod_excl = {mid: ex for mid, *_, ex in mods}

    def module_id(name, i):
        for f, t, mid in by_name.get(name, ()):
            if f <= i and (t is None or i < t):
                return mid
        return None

    def diff(parent, sha):
        """[(change, path, old_path, old_mode, new_mode, old_sha, new_sha, added, deleted)]"""
        args = [parent, sha] if parent else ["--root", sha]
        toks = git("diff-tree", "-r", "-M", "--raw", "--numstat", "-z", "--no-abbrev",
                   "--no-commit-id", *args).split(b"\0")
        toks = [x.decode("utf-8", "replace") for x in toks]
        raw, stats, k = [], {}, 0
        while k < len(toks):
            tok = toks[k]
            if not tok:
                k += 1
            elif tok.startswith(":"):
                om, nm_, osha, nsha, st = tok[1:].split(" ")
                if st[0] in "RC":
                    raw.append([st[0], toks[k + 2], toks[k + 1], om, nm_, osha, nsha])
                    k += 3
                else:
                    raw.append([{"T": "M"}.get(st[0], st[0]), toks[k + 1], None, om, nm_,
                                osha, nsha])
                    k += 2
            else:
                a, d, p = tok.split("\t", 2)
                if p:
                    k += 1
                else:
                    p = toks[k + 2]
                    k += 3
                stats[p] = (None if a == "-" else int(a), None if d == "-" else int(d))
        return [(*r, *stats.get(r[1], (None, None))) for r in raw]

    # ---------------------------------------------------------------- commits
    hist = []
    for line in git("log", "--first-parent", "--reverse", "--format=%H %P%x09%cI",
                    info["pinned_sha"]).decode().splitlines():
        ids, cdate = line.split("\t")
        s = ids.split()
        hist.append((s[0], s[1] if len(s) > 1 else None, len(s) - 1, cdate))
    dbc = q("SELECT i, sha, date, n_parents, n_files, is_format_only, is_agent "
            "FROM commits ORDER BY i")
    C.eq("commits.count", len(dbc), len(hist))
    n = min(len(dbc), len(hist))
    for (sha, _, np_, cd), (i, s2, d2, np2, *_ ) in zip(hist, dbc):
        C.eq("commits.sha", s2, sha, i)
        C.eq("commits.date", d2, cd, i)
        C.eq("commits.n_parents", np2, np_, i)

    def grouped(sql):
        out = defaultdict(list)
        for r in con.execute(sql):
            out[r[0]].append(r[1:])
        return out
    fc_rows = grouped("SELECT i, file_id, change, path, old_path, added, deleted, loc_after "
                      "FROM file_changes ORDER BY i, file_id")
    ri_rows = grouped("SELECT i, file_id, delta, stmt, kind FROM raw_imports")
    touch_rows = grouped("SELECT i, module_id, n_files FROM module_touches")
    fp_open = grouped("SELECT from_i, path, file_id FROM file_paths")
    fp_close = grouped("SELECT to_i, path, file_id FROM file_paths WHERE to_i IS NOT NULL")
    # churn tables come from SENSO-Lens' context/churn.py, which this repo does not include
    has_cc = bool(q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='commit_churn'"))
    cc_rows = {r[0]: r[1:] for r in q("SELECT i, n_files, added, deleted, lines, is_large "
                                      "FROM commit_churn")} if has_cc else {}
    have_churn = bool(cc_rows)

    # checkpoints
    k = max(1, args.checkpoints)
    checkpoints = sorted({round(j * (n - 1) / k) for j in range(k + 1)})

    def open_paths(i):
        return dict(q("SELECT path, file_id FROM file_paths WHERE from_i <= ? AND "
                      "(to_i IS NULL OR to_i > ?)", i, i))

    def replay_imports(i):
        out = defaultdict(Counter)
        for fid, stmt, kd, s in q("SELECT file_id, stmt, kind, SUM(delta) FROM raw_imports "
                                  "WHERE i <= ? GROUP BY file_id, stmt, kind "
                                  "HAVING SUM(delta) <> 0", i, ):
            out[fid][(stmt, kd)] = s
        return out

    py2_until = -1
    if info.get("py2_until"):
        r = q("SELECT MAX(i) FROM commits WHERE date < ?", info["py2_until"])[0][0]
        py2_until = -1 if r is None else r

    def resolve(t_py, pk, dirs, importer, stmt, i):
        """Target path of one import, following docs/schema.md section C, or None."""
        if stmt.startswith("import "):
            module, name, level = stmt[7:], None, 0
        else:
            m, name = stmt[5:].split(" import ", 1)
            level = len(m) - len(m.lstrip("."))
            module = m[level:]
        sub = name if name and name != "*" else None
        d = posixpath.dirname(importer)

        def cands(base, mod):
            stem = posixpath.join(base, *mod.split(".")) if mod else base
            out = [posixpath.join(stem, sub + ".py"), posixpath.join(stem, sub, "__init__.py")] \
                if sub else []
            out += [stem + ".py", posixpath.join(stem, "__init__.py")] if mod else \
                [posixpath.join(base, "__init__.py")]
            return out

        def first(cs):
            return next((p for p in cs if p in t_py), None)

        if level:
            base = d
            for _ in range(level - 1):
                if not base:
                    return None
                base = posixpath.dirname(base)
            return first(cands(base, module))
        stdlib = module.split(".", 1)[0] in STDLIB
        inside = [r for r in named_roots if importer.startswith(r + "/")] + [""]
        order = inside if stdlib else inside + [r for r in roots if r not in inside]
        for r in order:
            hit = first(cands(r, module))
            if hit:
                return hit
        if d in pk:
            sibling = not stdlib and i <= py2_until
        else:
            sibling = not any(importer.startswith(r + "/") for r in named_roots)
        return first(cands(d, module)) if sibling else None

    # churn windows
    start = date.fromisoformat(hist[0][3][:10])

    def windows(cd):
        day = date.fromisoformat(cd[:10])
        return [("month", day.strftime("%Y-%m")),
                ("90d", f"{max(0, (day - start).days) // WINDOW_DAYS:04d}")]
    last_of = {}
    for i, h in enumerate(hist[:n]):
        for w in windows(h[3]):
            last_of[w] = i
    ends = defaultdict(set)
    for w, i in last_of.items():
        ends[i].add(w)
    flags = {i: (np_ > 1, fo, ag) for i, _, _, np_, _, fo, ag in dbc}
    acc = defaultdict(lambda: defaultdict(lambda: [0] * 6))
    loc_truth = {}
    stats = Counter()

    prev_pk = set()
    for i in range(n):
        sha, p1, _, cd = hist[i]
        t = tree(sha)
        pk = pkgs(t)
        changes = diff(p1, sha)
        C.eq("commits.n_files", dbc[i][4], len(changes), i)

        # ---- file_changes (matched on path; for D the old path)
        db_fc = {r[2]: r for r in fc_rows.get(i, ())}
        fid_of = {}
        for ch, path, old, om, nm_, osha, nsha, a, d in changes:
            r = db_fc.pop(path, None)
            if r is None:
                C.eq("file_changes.row", None, [ch, path], i)
                continue
            fid, dch, _, dold, da, dd, dloc = r
            fid_of[path] = fid
            C.eq("file_changes.change", dch, ch, [i, path])
            C.eq("file_changes.old_path", dold, old, [i, path])
            C.eq("file_changes.added", da, a, [i, path])
            C.eq("file_changes.deleted", dd, d, [i, path])
            is_py = path.endswith(".py") and nm_ in PY_MODES and ch != "D"
            C.eq("file_changes.loc_after", dloc, loc(blob(nsha)) if is_py else None, [i, path])

            # ---- raw_imports
            old_py = (old or path).endswith(".py") and om in PY_MODES and ch not in ("A", "C")
            before = imports_of(osha) if old_py else Counter()
            after = imports_of(nsha) if is_py else Counter()
            if before is None or after is None:
                stats["raw_imports.skipped_unparseable"] += 1
                continue
            want = Counter()
            for key, c in (after - before).items():
                want[(1, *key)] += c
            for key, c in (before - after).items():
                want[(-1, *key)] += c
            got = Counter()
            for rfid, delta, stmt, kd in ri_rows.get(i, ()):
                if rfid == fid:
                    got[(delta, stmt, kd)] += 1
            C.eq("raw_imports.file", dict(got), dict(want), [i, path])
        for path, r in db_fc.items():
            C.eq("file_changes.row", [r[1], path], None, i)

        # ---- file_paths: what opens and closes here; a rename keeps the file id
        opened = Counter(p for ch, p, *_ in changes if ch in "ACR")
        closed = Counter((old if ch == "R" else p) for ch, p, old, *_ in changes if ch in "DR")
        C.eq("file_paths.opened", Counter(p for p, _ in fp_open.get(i, ())), opened, i)
        C.eq("file_paths.closed", Counter(p for p, _ in fp_close.get(i, ())), closed, i)
        gone = {p: fid for p, fid in fp_close.get(i, ())}
        for ch, p, old, *_ in changes:
            if ch == "R":
                C.eq("file_paths.rename_keeps_id", gone.get(old), fid_of.get(p), [i, old, p])

        # ---- module_touches and churn
        touched, per_mod = Counter(), Counter()
        nf = ad = de = 0
        for ch, path, old, om, nm_, osha, nsha, a, d in changes:
            deleted = ch == "D"
            dr = posixpath.dirname(path)
            if dr not in (prev_pk if deleted else pk):
                continue
            mid = module_id(modname(dr), i - 1 if deleted else i)
            if mid is None:
                stats["module.no_id"] += 1
                continue
            C.eq("modules.excluded", bool(mod_excl[mid]), is_excl(dr), [i, path])
            if is_excl(dr):
                continue
            touched[mid] += 1
            if path.endswith(".py"):
                nf += 1
                ad += a or 0
                de += d or 0
                per_mod[mid] += (a or 0) + (d or 0)
        C.sets("module_touches", {m: c for m, c in touch_rows.get(i, ())}, dict(touched), i)
        lines = ad + de
        large = int(nf >= LARGE_FILES or lines >= LARGE_LINES)
        if have_churn:
            C.eq("commit_churn", list(cc_rows.get(i, ())), [nf, ad, de, lines, large], i)
        is_merge, fo, ag = flags[i]
        for m, c in per_mod.items():
            for w in windows(cd):
                r = acc[w][m]
                for j, v in enumerate((1, c, c * is_merge, c * fo, c * large, c * ag)):
                    r[j] += v
        if ends.get(i):
            locs = Counter()
            for p, (mode, obj) in t.items():
                dr = posixpath.dirname(p)
                if p.endswith(".py") and dr in pk and mode in PY_MODES:
                    mid = module_id(modname(dr), i)
                    if mid is not None:
                        locs[mid] += loc(blob(obj))
            for w in ends[i]:
                for m in acc[w]:
                    loc_truth[(w, m)] = locs.get(m, 0)

        # ---- checkpoints: paths, modules, membership, edges
        if i in checkpoints:
            live = open_paths(i)
            C.sets("file_paths.open", {p: True for p in live}, {p: True for p in t}, i)
            open_mods = {nm for mid, nm, f, to, _ in mods if f <= i and (to is None or to > i)}
            C.sets("modules.open", {m: True for m in open_mods},
                   {modname(d): True for d in pk}, i)
            fm = dict(q("SELECT file_id, module_id FROM file_modules WHERE from_i <= ? AND "
                        "(to_i IS NULL OR to_i > ?)", i, i))
            my_mod = {}
            for p in t:
                dr = posixpath.dirname(p)
                my_mod[p] = modname(dr) if dr in pk else None
            C.sets("file_modules", {p: mod_name.get(fm.get(fid)) for p, fid in live.items()},
                   {p: my_mod[p] for p in t}, i)

            # file graph from scratch
            t_py = {p for p, (mode, _) in t.items() if p.endswith(".py")}
            replay = None
            mine = Counter()
            for p in sorted(t_py):
                mode, obj = t[p]
                imps = imports_of(obj) if mode in PY_MODES else Counter()
                if imps is None:
                    stats["edges.fallback_files"] += 1
                    replay = replay or replay_imports(i)
                    imps = replay.get(live.get(p), Counter())
                for (stmt, kd), c in imps.items():
                    dst = resolve(t_py, pk, None, p, stmt, i)
                    if dst and dst != p:
                        mine[(p, dst, kd)] += c
            path_of = {fid: p for p, fid in live.items()}
            dbe = {(path_of.get(s), path_of.get(d), kd): w for s, d, kd, w in q(
                "SELECT src_file, dst_file, kind, SUM(delta) FROM file_edges WHERE i <= ? "
                "GROUP BY src_file, dst_file, kind HAVING SUM(delta) <> 0", i)}
            C.sets("file_edges", dbe, dict(mine), i)
            stats["file_edges.weight_at_last"] = sum(mine.values())

            lifted = Counter()
            for (s, d, kd), w in mine.items():
                sd, dd = posixpath.dirname(s), posixpath.dirname(d)
                if sd not in pk or dd not in pk:
                    continue
                sm, dm = modname(sd), modname(dd)
                if sm == dm or is_excl(sd) or is_excl(dd):
                    continue
                lifted[(sm, dm, kd)] += w
            dbm = {(mod_name[s], mod_name[d], kd): w for s, d, kd, w in q(
                "SELECT src_mod, dst_mod, kind, SUM(delta) FROM module_edges WHERE i <= ? "
                "GROUP BY src_mod, dst_mod, kind HAVING SUM(delta) <> 0", i)}
            C.sets("module_edges", dbm, dict(lifted), i)
        prev_pk = pk

    # ---------------------------------------------------------------- module_churn
    if have_churn:
        mc = {(r[0], r[1], r[2]): list(r[3:]) for r in q("SELECT * FROM module_churn")}
        truth = {}
        for (kd, w), ms in acc.items():
            for m, r in ms.items():
                le = loc_truth[((kd, w), m)]
                truth[(kd, w, m)] = [*r, le, round(r[1] / le, 6) if le > 0 else None]
        C.sets("module_churn", mc, truth)
    cat.stdin.close()
    cat.wait()

    report = {
        "repo": info["repo"], "commits": n, "checkpoints": len(checkpoints),
        "seconds": round(time.time() - t0),
        "checked": dict(C.n), "mismatches": dict(C.bad), "notes": dict(stats),
        "examples": {k: v for k, v in C.ex.items()},
    }
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clone")
    ap.add_argument("db")
    ap.add_argument("--out")
    ap.add_argument("--checkpoints", type=int, default=25)
    a = ap.parse_args(argv)
    rep = run(a)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rep, f, indent=1, default=str)
    bad = sum(rep["mismatches"].values())
    print(f"{rep['repo']}: {rep['commits']} commits, {sum(rep['checked'].values())} values "
          f"checked, {bad} mismatches {rep['mismatches'] or ''} {rep['notes']} "
          f"in {rep['seconds']}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
