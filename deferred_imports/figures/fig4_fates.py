"""Fig. 4 (RQ2): fate of each project's deferred-only pairs, one 100% stacked bar each.

Three parts: promoted, removed, and still deferred-only. Sorted by share promoted;
"All" at the bottom. The command-line summary includes the promotion subtypes.
Inputs: CSVs from `analysis.fate --csv` and `analysis.promotion_kinds --csv`.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from deferred_imports.figures import style

PROMOTION_PARTS = ("promoted_clean", "promoted_dead", "promoted_other")
FATE_PARTS = (*PROMOTION_PARTS, "removed", "kept")
PLOT_PARTS = [
    (PROMOTION_PARTS, "Promoted"),
    (("removed",), "Removed"),
    (("kept",), "Still deferred-only"),
]
PALETTES = {
    "grayscale": ("0.12", "0.76", "0.94"),
    "color": ("#185ABC", "#E5B956", "#F3F4F6"),
}


def fate_rows(fate_csv: Path, kinds_csv: Path) -> list[dict]:
    """Per repo counts of the five parts, plus an 'All' row."""
    with open(kinds_csv, newline="") as f:
        left = {r["repo"]: (int(r["same_name_left"]), int(r["different_name_left"]))
                for r in csv.DictReader(f) if r["repo"] != "ALL"}
    rows = []
    with open(fate_csv, newline="") as f:
        for r in csv.DictReader(f):
            prom = int(r["promoted"])
            dead, other = left.get(r["repo"], (0, 0))
            rows.append({"repo": r["repo"], "promoted_clean": prom - dead - other,
                         "promoted_dead": dead, "promoted_other": other,
                         "removed": int(r["removed"]), "kept": int(r["kept"])})
    total = {k: sum(r[k] for r in rows) for k in FATE_PARTS}
    for r in rows + [total]:
        r["n"] = sum(r[k] for k in FATE_PARTS)
    rows.sort(key=lambda r: -sum(r[k] for k in PROMOTION_PARTS)
              / (r["n"] or 1))
    return rows + [{"repo": "All", **total}]


def draw_fates(rows: list[dict], out: Path, width: float = style.COLUMN, *,
               palette: str = "grayscale") -> None:
    plt = style.plt()
    h = 0.13 * len(rows) + 0.6
    fig, ax = plt.subplots(figsize=(width, h))
    y = np.arange(len(rows))[::-1]
    left = np.zeros(len(rows))
    for (keys, label), fill in zip(PLOT_PARTS, PALETTES[palette], strict=True):
        share = np.array([sum(r[k] for k in keys) / r["n"] if r["n"] else 0 for r in rows])
        ax.barh(y, share, left=left, color=fill, edgecolor="black", lw=0.3, height=0.75,
                label=label)
        left += share
    ax.set_yticks(y, [f"{r['repo']} ({r['n']:,})" for r in rows], fontsize=6.5)
    ax.get_yticklabels()[-1].set_fontweight("bold")
    ax.axhline(0.5, color="black", lw=0.6)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.legend(ncol=1, frameon=False, loc="lower center", bbox_to_anchor=(0.4, 1.0),
              handlelength=1, labelspacing=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fate", type=Path, required=True, help="CSV from fate --csv")
    ap.add_argument("--kinds", type=Path, required=True, help="CSV from promotion_kinds --csv")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig4-fates.pdf"))
    ap.add_argument("--palette", choices=PALETTES, default="grayscale")
    a = ap.parse_args(argv)
    rows = fate_rows(a.fate, a.kinds)
    for r in rows:
        print(r["repo"], r["n"], *(f"{k}={r[k]} ({r[k] / r['n']:.1%})" for k in FATE_PARTS))
    draw_fates(rows, a.out, palette=a.palette)


if __name__ == "__main__":
    main()
