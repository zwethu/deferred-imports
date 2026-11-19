#!/usr/bin/env bash
# Run the whole experiment on the 24 repositories in corpus/paper-corpus.csv:
#   0. preflight: miner 0.4.0, tests pass, Python 2 cut-off dates filled in
#   1. clone (or fetch) every repository into ../clones
#   2. mine each one at its pinned commit, with check.py after each
#   3. E1 (graphs), E3 (cycles), E2 (fate) at package and file level
#   4. the R3 hand-check lists: samples of 60 (handcheck/) and every case (handcheck_all/)
# Run from the repo root:
#     bash scripts/run_experiment.sh
# Safe to start again after a stop: finished repositories are skipped and a stopped one
# continues. Settings: JOBS (default 4), OUT (default out/<today>), CLONES (default ../clones).
set -euo pipefail
JOBS="${JOBS:-4}"
OUT="${OUT:-out/$(date +%Y-%m-%d)}"
export CLONES="${CLONES:-../clones}"

echo "== 0. preflight"
version=$(uv run python -c "from deferred_imports.mining.mine import MINER_VERSION; print(MINER_VERSION)")
if [ "$version" != "0.4.0" ]; then echo "!! miner is $version, need 0.4.0"; exit 1; fi
uv run pytest -q
uv run python - <<'EOF'
import csv, sys
# Repositories with Python 2 code early in their history (docs/corpus.md).
need = {"numpy", "oq-engine", "osf.io", "Sefaria-Project", "kpi", "the-blue-alliance"}
have = {r["name"] for r in csv.DictReader(open("corpus/resolver.csv")) if r["py2_until"]}
missing = sorted(need - have)
if missing:
    print("!! no py2_until in corpus/resolver.csv for: " + ", ".join(missing))
    print("   The miner saves this date when it starts a repository; fill it in first.")
    sys.exit(1)
EOF

echo "== 1. clone into $CLONES"
bash scripts/clone_corpus.sh

echo "== 2. mine and check (logs in index/<repo>.log)"
uv run python -m deferred_imports.mining.mine_corpus --clones "$CLONES" --jobs "$JOBS" --check

echo "== 3. E1, E3, E2 -> $OUT"
mkdir -p "$OUT"
dbs=()  # index/<name>.sqlite for the corpus repositories only (bash 3.2 has no mapfile)
while read -r db; do dbs+=("$db"); done < <(uv run python -c 'import csv
for r in csv.DictReader(open("corpus/paper-corpus.csv")): print("index/" + r["name"] + ".sqlite")')
for level in package file; do
  uv run python -m deferred_imports.analysis.graphs "${dbs[@]}" --level "$level" --csv "$OUT/e1_$level.csv"
  uv run python -m deferred_imports.analysis.cycles "${dbs[@]}" --level "$level" --csv "$OUT/e3_$level.csv"
  uv run python -m deferred_imports.analysis.fate "${dbs[@]}" --level "$level" \
      --csv "$OUT/e2_$level.csv" --episodes "$OUT/e2_episodes_$level.csv"
done

echo "== 4. R3 hand-check lists -> $OUT/handcheck"
uv run python -m deferred_imports.analysis.handcheck "${dbs[@]}" --out "$OUT/handcheck" --n 60
uv run python -m deferred_imports.analysis.handcheck "${dbs[@]}" --out "$OUT/handcheck_all" --n 0

echo "done: results in $OUT"
