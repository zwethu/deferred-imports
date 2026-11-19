"""RQ1 share chart: share of each project's file pairs that exist only through deferred imports.

One bar per project, largest first, median marked. Input: the CSV from
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv share.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from deferred_imports.figures import style

BAR_COLOR = "#1f4e79"          # same blue as the in-function curve in fig3_km


def share_rows(share_csv: Path) -> list[dict]:
    """[{'repo', 'pairs', 'deferred', 'share'}], largest share first."""
    with open(share_csv, newline="") as f:
        rows = [{"repo": r["repo"], "pairs": int(r["pairs"]), "deferred": int(r["pairs_deferred_only"])}
                for r in csv.DictReader(f)]
    for r in rows:
        r["share"] = r["deferred"] / r["pairs"] if r["pairs"] else 0.0
    return sorted(rows, key=lambda r: -r["share"])


def draw_share(rows: list[dict], out: Path, width: float = style.COLUMN) -> None:
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, 0.13 * len(rows) + 0.5))
    y = np.arange(len(rows))[::-1]
    share = np.array([r["share"] for r in rows])
    med = float(np.median(share))
    ax.barh(y, share, color=BAR_COLOR, height=0.7, zorder=2)
    for yy, v in zip(y, share):
        ax.text(v + 0.004, yy, f"{v:.1%}", va="center", fontsize=6, color="0.3", zorder=4,
                bbox={"boxstyle": "square,pad=0.1", "fc": "white", "ec": "none"})
    ax.axvline(med, color="0.25", lw=0.8, ls=(0, (3, 2)), zorder=3)
    ax.text(med + 0.004, len(rows) - 0.3, f"median {med:.1%}", fontsize=6.5, color="0.25", va="bottom")
    ax.set_yticks(y, [r["repo"] for r in rows], fontsize=6.5)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.6, len(rows) + 0.4)
    ax.set_xlim(0, max(share) * 1.15)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_xlabel("Share of file pairs that are deferred-only (last commit)")
    ax.grid(axis="x", color="0.9", lw=0.5)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--share", type=Path, required=True, help="CSV from graphs --level file --csv")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig-share.pdf"))
    a = ap.parse_args(argv)
    rows = share_rows(a.share)
    for r in rows:
        print(f"{r['repo']} {r['deferred']}/{r['pairs']} = {r['share']:.1%}")
    print(f"median {float(np.median([r['share'] for r in rows])):.1%}")
    draw_share(rows, a.out)


if __name__ == "__main__":
    main()
