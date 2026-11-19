#!/usr/bin/env bash
# Check every mined database in index/ against git with the independent verifier
# (deferred_imports.mining.verify: Python ast instead of tree-sitter, graphs rebuilt from scratch).
# Read-only on the databases and the clones. One JSON report per project, plus a summary.
#
# Usage (from the repo root):  bash scripts/verify_all.sh [clones_dir] [jobs]
#   clones_dir  default ../clones   (one clone per project, named like index/<name>.sqlite)
#   jobs        default 4           (projects verified in parallel)
set -euo pipefail
CLONES=${1:-../clones}
JOBS=${2:-4}
OUT=out/verify
mkdir -p "$OUT"

ls index/*.sqlite | xargs -P "$JOBS" -I{} bash -c '
  db="$1"; name=$(basename "$db" .sqlite)
  uv run python -m deferred_imports.mining.verify "$2/$name" "$db" \
      --out "$3/$name.json" > "$3/$name.log" 2>&1 || true
  tail -1 "$3/$name.log"
' _ {} "$CLONES" "$OUT"

uv run python - "$OUT" <<'EOF'
import csv, json, sys
from pathlib import Path
out = Path(sys.argv[1])
rows = []
for db in sorted(Path("index").glob("*.sqlite"), key=lambda p: p.stem.lower()):
    rep = out / f"{db.stem}.json"
    if not rep.exists():
        rows.append({"project": db.stem, "checkpoints": "", "commits": "", "values_checked": "",
                     "mismatches": "", "result": "NO REPORT (see log)"})
        continue
    r = json.loads(rep.read_text())
    bad = sum(r["mismatches"].values())
    rows.append({"project": r["repo"], "checkpoints": r["checkpoints"], "commits": r["commits"],
                 "values_checked": sum(r["checked"].values()), "mismatches": bad,
                 "result": "PASS" if bad == 0 else "FAIL"})
with open(out / "summary.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
ok = sum(r["result"] == "PASS" for r in rows)
print(f"{ok}/{len(rows)} projects PASS; summary in {out / 'summary.csv'}")
EOF
