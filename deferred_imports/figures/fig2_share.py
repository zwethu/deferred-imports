"""Fig. 2 (RQ1): share of each project's file pairs that are deferred-only, split by kind.

One horizontal bar per project, sorted by share. Each bar is split into in-function pairs
(at least one in-function import) and type-only pairs (only TYPE_CHECKING imports), so the
share and the mix of kinds show together. Dashed line: per-project median.
Input: the CSV from
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv share.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from deferred_imports.figures import style

IN_FUNCTION_COLOR = "#1f4e79"   # same colours as the bars in fig5_km
TYPE_ONLY_COLOR = "#d95f02"


def share_rows(share_csv: Path) -> list[dict]:
    """[{'repo', 'pairs', 'deferred', 'in_function', 'type_only', 'share'}], largest share first."""
    rows = []
    with open(share_csv, newline="") as f:
        for r in csv.DictReader(f):
            pairs, deferred, type_only = (int(r["pairs"]), int(r["pairs_deferred_only"]),
                                          int(r["pairs_type_only"]))
            rows.append({"repo": r["repo"], "pairs": pairs, "deferred": deferred,
                         "in_function": deferred - type_only, "type_only": type_only,
                         "share": deferred / pairs if pairs else 0.0})
    return sorted(rows, key=lambda r: (-r["share"], r["repo"].lower()))


def draw_share(rows: list[dict], out: Path, width: float = style.COLUMN) -> None:
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, 0.13 * len(rows) + 0.7))
    y = np.arange(len(rows))[::-1]
    inf = np.array([r["in_function"] / r["pairs"] if r["pairs"] else 0 for r in rows])
    typ = np.array([r["type_only"] / r["pairs"] if r["pairs"] else 0 for r in rows])
    share = inf + typ
    med = float(np.median([r["share"] for r in rows]))
    ax.barh(y, inf, height=0.72, color=IN_FUNCTION_COLOR, label="In-function", zorder=2)
    ax.barh(y, typ, left=inf, height=0.72, color=TYPE_ONLY_COLOR, label="Type-only", zorder=2)
    for yy, v in zip(y, share):
        ax.text(v + 0.004, yy, f"{v:.1%}", va="center", fontsize=6, color="0.25", zorder=5,
                bbox={"boxstyle": "square,pad=0.08", "fc": "white", "ec": "none"})
    ax.axvline(med, color="0.3", lw=0.7, ls=(0, (3, 2)), zorder=3)
    ax.text(med + 0.004, -0.9, f"median {med:.1%}", fontsize=6.5, color="0.3", va="center")
    ax.set_yticks(y, [r["repo"] for r in rows], fontsize=6.5)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-1.3, len(rows) - 0.4)
    ax.set_xlim(0, max(share) * 1.15)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_xlabel("% of module pairs that are deferred-only")
    ax.grid(axis="x", color="0.9", lw=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", ncol=1, handlelength=1)
    ax.spines[["top", "right", "left"]].set_visible(False)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--share", type=Path, required=True, help="CSV from graphs --level file --csv")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig2-share.pdf"))
    a = ap.parse_args(argv)
    rows = share_rows(a.share)
    for r in rows:
        kinds = r["in_function"] + r["type_only"]
        typ = r["type_only"] / kinds if kinds else 0
        print(f"{r['repo']}: {r['deferred']}/{r['pairs']} = {r['share']:.1%} "
              f"(in-function {r['in_function']}, type-only {r['type_only']} = {typ:.0%} type-only)")
    tot = {k: sum(r[k] for r in rows) for k in ("pairs", "deferred", "in_function", "type_only")}
    print(f"all: {tot['deferred']}/{tot['pairs']} = {tot['deferred'] / tot['pairs']:.1%}; "
          f"in-function {tot['in_function']} ({tot['in_function'] / tot['deferred']:.1%}), "
          f"type-only {tot['type_only']} ({tot['type_only'] / tot['deferred']:.1%}); "
          f"median per project {float(np.median([r['share'] for r in rows])):.1%}; "
          f"above 15%: {', '.join(r['repo'] for r in rows if r['share'] > 0.15)}")
    draw_share(rows, a.out)


if __name__ == "__main__":
    main()
