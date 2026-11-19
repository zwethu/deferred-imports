"""RQ1 stability: mean and median per-project share of deferred-only file pairs, with
95% percentile bootstrap confidence intervals (projects resampled with replacement).

Input: the CSV from
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv share.csv
Run:
    uv run python -m deferred_imports.analysis.bootstrap share.csv [--resamples 10000] [--seed 1]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def shares(share_csv: Path) -> np.ndarray:
    """Per-project share of file pairs that are deferred-only (projects with no pairs dropped)."""
    with open(share_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    return np.array([int(r["pairs_deferred_only"]) / int(r["pairs"]) for r in rows if int(r["pairs"])])


def bootstrap_ci(values, stat, resamples: int = 10_000, seed: int = 1, level: float = 0.95):
    """(point estimate, low, high): percentile bootstrap CI of `stat` over `values`."""
    v = np.asarray(values, float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(v, size=(resamples, len(v)), replace=True)
    boot = stat(draws, axis=1)
    a = (1 - level) / 2
    lo, hi = np.percentile(boot, [100 * a, 100 * (1 - a)])
    return float(stat(v)), float(lo), float(hi)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("share_csv", type=Path)
    ap.add_argument("--resamples", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=1)     # seed 1, as stated in the paper
    a = ap.parse_args(argv)
    s = shares(a.share_csv)
    print(f"projects: {len(s)}, resamples: {a.resamples}, seed: {a.seed}")
    for name, stat in (("mean", np.mean), ("median", np.median)):
        est, lo, hi = bootstrap_ci(s, stat, a.resamples, a.seed)
        print(f"{name} share of deferred-only pairs: {est:.1%} (95% bootstrap CI {lo:.1%}-{hi:.1%})")


if __name__ == "__main__":
    main()
