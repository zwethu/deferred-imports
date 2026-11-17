"""Check one mined repository against git itself.

    uv run python -m deferred_imports.mining.check ../corpus-clones/netbox index/netbox.sqlite

Everything is compared at the last mined commit:
1. Files: the open paths in file_paths must be exactly the files git lists there.
2. Replay: summing every raw_imports row per file id must give exactly the imports of
   every .py file there.
3. tree-sitter vs Python `ast` on every .py file there.
4. Every first-parent merge: the number of changed files equals `git diff ^1`.
5. Edges: summing file_edges and module_edges must give exactly the graph that edges.py builds
   from scratch from the files and imports git has there, and the open modules must match.
6. LOC: the last loc_after logged for each .py file equals its line count there.
"""

import ast
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from deferred_imports.mining.edges import Graph, settings_of
from deferred_imports.mining.mine import extract_imports, is_py, split_stmt


def ast_imports(src: bytes) -> Counter | None:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    out = Counter()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for x in n.names:
                out[f"import {x.name}"] += 1
        elif isinstance(n, ast.ImportFrom) and n.module != "__future__":
            for x in n.names:
                out[f"from {'.' * n.level}{n.module or ''} import {x.name}"] += 1
    return out


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    repo, db = Path(argv[0]), Path(argv[1])
    if not db.exists():
        print(f"no database at {db}")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    last_i, sha = con.execute("SELECT i, sha FROM commits ORDER BY i DESC LIMIT 1").fetchone()

    def git(*args: str) -> bytes:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              check=True).stdout

    # 1. files
    live = dict(con.execute("SELECT path, file_id FROM file_paths WHERE to_i IS NULL"))
    tree = {}
    for line in git("-c", "core.quotepath=off", "ls-tree", "-r", "-z", sha).split(b"\x00"):
        if line:
            meta, path = line.decode("utf-8", "replace").split("\t", 1)
            tree[path] = meta.split()  # mode, type, sha
    path_bad = sorted(set(live) ^ set(tree))

    # 2. replay
    state = defaultdict(Counter)
    rows = con.execute("SELECT file_id, stmt, kind, SUM(delta) FROM raw_imports "
                       "GROUP BY file_id, stmt, kind HAVING SUM(delta) <> 0")
    for fid, stmt, kind, n in rows:
        state[fid][(stmt, kind)] = n

    truth, loc_truth, ast_diff, ast_files, examples = {}, {}, 0, 0, []
    for path, (mode, _, blob) in tree.items():
        if not is_py(path, mode):
            continue
        src = git("cat-file", "blob", blob)
        imps, _ = extract_imports(src)
        if path in live:
            loc_truth[live[path]] = src.count(b"\n") + (bool(src) and not src.endswith(b"\n"))
            if imps:
                truth[live[path]] = imps
        # 3. ast
        a = ast_imports(src)
        if a is None:
            continue
        ast_files += 1
        ts = Counter(k for k, _ in imps.elements())
        if a != ts:
            ast_diff += 1
            if len(examples) < 5:
                examples.append((path, dict(a - ts), dict(ts - a)))
    name = {fid: path for path, fid in live.items()}
    replay_bad = sorted(name.get(fid, f"file_id {fid}") for fid in set(state) | set(truth)
                        if state.get(fid) != truth.get(fid))

    # 4. merges
    merges = merge_bad = 0
    for msha, n_files in con.execute("SELECT sha, n_files FROM commits WHERE n_parents > 1"):
        merges += 1
        names = git("diff", "--name-only", "-M", f"{msha}^1", msha).split(b"\n")
        merge_bad += len([n for n in names if n]) != n_files

    # 5. edges
    built = con.execute("SELECT 1 FROM run_info WHERE key = 'edges_version'").fetchone()
    g = Graph(*settings_of(con))
    g.step(last_i, [(fid, "A", path, None) for path, fid in sorted(live.items(), key=lambda x: x[1])],
           sorted(((fid, 1, stmt, *split_stmt(stmt), kind) for fid, imps in truth.items()
                   for (stmt, kind), n in imps.items() for _ in range(n)),
                  key=lambda r: (r[0], r[2], r[6])))
    db_files = Counter({(s, d, k): w for s, d, k, w in con.execute(
        "SELECT src_file, dst_file, kind, SUM(delta) FROM file_edges GROUP BY 1, 2, 3 "
        "HAVING SUM(delta) <> 0")})
    db_mods = Counter({(s, d, k): w for s, d, k, w in con.execute(
        "SELECT ms.name, md.name, e.kind, SUM(e.delta) FROM module_edges e "
        "JOIN modules ms ON ms.module_id = e.src_mod JOIN modules md ON md.module_id = e.dst_mod "
        "GROUP BY 1, 2, 3 HAVING SUM(e.delta) <> 0")})
    open_mods = {n for (n,) in con.execute("SELECT name FROM modules WHERE to_i IS NULL")}
    scratch_files, scratch_mods = g.file_weights(), g.module_weights()
    file_bad = [(name.get(s, s), name.get(d, d), k, db_files[(s, d, k)], scratch_files[(s, d, k)])
                for s, d, k in sorted(set(db_files) | set(scratch_files))
                if db_files[(s, d, k)] != scratch_files[(s, d, k)]]
    mod_bad = [(s, d, k, db_mods[(s, d, k)], scratch_mods[(s, d, k)])
               for s, d, k in sorted(set(db_mods) | set(scratch_mods))
               if db_mods[(s, d, k)] != scratch_mods[(s, d, k)]]
    mods_bad = sorted(open_mods ^ set(g.modules))
    edges_ok = built is not None and not file_bad and not mod_bad and not mods_bad

    # 6. LOC: replay loc_after per file id (NULL for a delete or a file that is not .py)
    loc = {}
    for fid, n in con.execute("SELECT file_id, loc_after FROM file_changes ORDER BY i, file_id"):
        if n is None:
            loc.pop(fid, None)
        else:
            loc[fid] = n
    loc = {fid: n for fid, n in loc.items() if fid in name}
    loc_bad = sorted(name.get(fid, f"file_id {fid}") for fid in set(loc) | set(loc_truth)
                     if loc.get(fid) != loc_truth.get(fid))

    ok = not path_bad and not replay_bad and not merge_bad and edges_ok and not loc_bad
    print(f"files:   {len(tree)} in git at {sha[:12]}, {len(path_bad)} differ {path_bad[:5]}")
    print(f"replay:  {len(truth)} files with imports, {len(replay_bad)} differ {replay_bad[:5]}")
    print(f"loc:     {len(loc_truth)} .py files, {len(loc_bad)} differ {loc_bad[:5]}")
    print(f"ast:     {ast_diff} of {ast_files} files differ from tree-sitter")
    for ex in examples:
        print("         ", ex)
    print(f"merges:  {merges}, {merge_bad} with a file count different from git diff ^1")
    if built is None:
        print("edges:   not built (run python -m deferred_imports.mining.edges on the database)")
    else:
        print(f"edges:   {len(scratch_files)} file edges, {len(file_bad)} differ {file_bad[:3]}")
        print(f"         {len(scratch_mods)} module edges, {len(mod_bad)} differ {mod_bad[:3]}")
        print(f"         {len(g.modules)} modules, {len(mods_bad)} differ {mods_bad[:5]}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
