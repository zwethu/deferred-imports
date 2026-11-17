"""Mine every repo in corpus/repos.csv at its pinned SHA, smallest first, N at a time.

    uv run python -m deferred_imports.mining.mine_corpus --clones ~/senso-clones --jobs 4

A repo whose index/<name>.sqlite is complete is skipped, and an incomplete one continues
where it stopped, so a stopped run can simply be started again. Each repo's log goes to
index/<name>.log. Repos that fail are listed at the end; nothing else is retried.
"""

import argparse
import csv
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def is_complete(db: Path) -> bool:
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        done = con.execute("SELECT 1 FROM run_info WHERE key = 'finished'").fetchone()
        con.close()
        return done is not None
    except sqlite3.Error:
        return False


def run_one(row: dict, clones: Path, out: Path, salt: Path, check: bool) -> tuple[str, str]:
    name = row["name"]
    db = out / f"{name}.sqlite"
    if is_complete(db):
        return name, "skipped (already mined)"
    repo = clones / name
    if not repo.is_dir():
        return name, f"FAILED: no clone at {repo}"
    log = out / f"{name}.log"
    t0 = time.time()
    with open(log, "w") as f:
        cmd = [sys.executable, "-m", "deferred_imports.mining.mine", str(repo),
               "--rev", row["pinned_sha"], "--out", str(db), "--salt-file", str(salt)]
        if subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                          check=False).returncode != 0:
            return name, f"FAILED: see {log} (the next start continues it)"
        if check:
            cmd = [sys.executable, "-m", "deferred_imports.mining.check", str(repo), str(db)]
            if subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                          check=False).returncode != 0:
                return name, f"mined, CHECK FAILED: see {log}"
    return name, f"ok in {time.time() - t0:.0f}s"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", type=Path, default=Path("corpus/repos.csv"))
    ap.add_argument("--clones", type=Path, default=Path.home() / "senso-clones")
    ap.add_argument("--out", type=Path, default=Path("index"))
    ap.add_argument("--salt-file", type=Path, default=Path(".salt"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", nargs="*", help="mine only these repo names")
    ap.add_argument("--check", action="store_true", help="run the check after each repo")
    a = ap.parse_args(argv)

    with open(a.repos, newline="") as f:
        rows = list({r["name"]: r for r in csv.DictReader(f)}.values())  # drop duplicate rows
    if a.only:
        rows = [r for r in rows if r["name"] in a.only]
    rows.sort(key=lambda r: int(r["first_parent_commits"] or 0))
    a.out.mkdir(parents=True, exist_ok=True)
    if not a.salt_file.exists():  # create once here, not in 4 processes at the same time
        from deferred_imports.mining.mine import load_salt
        load_salt(a.salt_file)

    print(f"{len(rows)} repos, {a.jobs} at a time", flush=True)
    failed = []
    with ThreadPoolExecutor(a.jobs) as pool:
        futures = [pool.submit(run_one, r, a.clones, a.out, a.salt_file, a.check) for r in rows]
        for fut in as_completed(futures):
            name, status = fut.result()
            print(f"{name:28} {status}", flush=True)
            if "FAIL" in status:
                failed.append(name)
    if failed:
        print("failed:", " ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
