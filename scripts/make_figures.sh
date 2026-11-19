#!/usr/bin/env bash
# Make every figure in the paper from the mined databases in index/.
# Usage (from the repo root):  bash scripts/make_figures.sh
set -euo pipefail
OUT=out/figures
mkdir -p "$OUT"

# RQ1 share per project, and its bootstrap confidence intervals (numbers in the text)
uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv "$OUT/share.csv"
uv run python -m deferred_imports.analysis.bootstrap "$OUT/share.csv" | tee "$OUT/bootstrap.txt"

# RQ1 hidden cycles: files in a cycle without and with deferred imports
uv run python -m deferred_imports.analysis.cycles index/*.sqlite --level file --csv "$OUT/cycles.csv"
uv run python -m deferred_imports.figures.table1_subjects --share "$OUT/share.csv" \
    --cycles "$OUT/cycles.csv" --out "$OUT/table1-subjects.tex"

# data behind Fig. 3 and Fig. 4
uv run python -m deferred_imports.analysis.fate index/*.sqlite --level file \
    --csv "$OUT/fate.csv" --episodes "$OUT/episodes.csv"
uv run python -m deferred_imports.analysis.promotion_kinds index/*.sqlite --csv "$OUT/kinds.csv"

for ext in pdf png; do
  uv run python -m deferred_imports.figures.fig1_pipeline --out "$OUT/fig1-pipeline.$ext"
  uv run python -m deferred_imports.figures.fig2_cycle index/django.sqlite \
      --src django/urls/resolvers.py --dst django/conf/urls/__init__.py --strip django/ \
      --out "$OUT/fig2-cycle.$ext"
  uv run python -m deferred_imports.figures.fig_hidden_cycles --cycles "$OUT/cycles.csv" \
      --out "$OUT/fig-hidden-cycles.$ext"
  uv run python -m deferred_imports.figures.fig3_km "$OUT/episodes.csv" --out "$OUT/fig3-km.$ext"
  uv run python -m deferred_imports.figures.fig4_fates --fate "$OUT/fate.csv" \
      --kinds "$OUT/kinds.csv" --out "$OUT/fig4-fates.$ext"
done
