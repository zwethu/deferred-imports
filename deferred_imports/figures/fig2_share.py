"""Fig. 2 (RQ1): deferred-only pairs across all 24 projects, pooled, as three donuts.

1. all module pairs at the last commit: deferred-only vs eager-linked;
2. the deferred-only pairs by kind: in-function vs type-only;
3. the same deferred-only pairs: do they close a cycle in the full graph?
Per-project numbers are in Table I (and fig_share_by_project.py, not in the paper).
Inputs: the CSVs from
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv share.csv
    uv run python -m deferred_imports.analysis.cycles index/*.sqlite --level file --csv cycles.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style

IN_FUNCTION_COLOR = "#1f4e79"   # same blue / orange as fig5_km and Table I's kinds
TYPE_ONLY_COLOR = "#d95f02"
ACCENT = "#8c1c13"              # deferred-only (donut 1) and "closes a cycle" (donut 3)
ACCENT_LIGHT = "#e3b3ad"
EAGER_COLOR = "0.86"


def totals(share_csv: Path, cycles_csv: Path) -> dict:
    """Corpus totals: pairs, eager, deferred-only, in-function, type-only, closing, not closing."""
    with open(share_csv, newline="") as f:
        s = list(csv.DictReader(f))
    with open(cycles_csv, newline="") as f:
        c = list(csv.DictReader(f))
    t = {"pairs": sum(int(r["pairs"]) for r in s),
         "deferred": sum(int(r["pairs_deferred_only"]) for r in s),
         "type_only": sum(int(r["pairs_type_only"]) for r in s),
         "closing": sum(int(r["deferred_only_closing_cycle"]) for r in c)}
    if sum(int(r["deferred_only_pairs"]) for r in c) != t["deferred"]:
        raise SystemExit("share.csv and cycles.csv disagree on the number of deferred-only pairs")
    t["eager"] = t["pairs"] - t["deferred"]
    t["in_function"] = t["deferred"] - t["type_only"]
    t["not_closing"] = t["deferred"] - t["closing"]
    return t


def _donut(ax, parts, centre, title, legend):
    """parts: [(value, colour, pull-out)], first part starts at 12 o'clock, clockwise."""
    vals = [v for v, _, _ in parts]
    ax.pie(vals, colors=[c for _, c, _ in parts], explode=[e for _, _, e in parts],
           startangle=90, counterclock=False,
           wedgeprops={"width": 0.36, "edgecolor": "white", "linewidth": 0.8})
    ax.text(0, 0, centre, ha="center", va="center", fontweight="bold",
            fontsize=7 if "\n" in centre else 9, linespacing=1.1)
    ax.text(0.5, -0.04, title, transform=ax.transAxes, ha="center", va="top", fontsize=7,
            linespacing=1.15)
    ax.text(0.5, -0.36, legend, transform=ax.transAxes, ha="center", va="top", fontsize=6,
            color="0.3", linespacing=1.2)
    ax.set_aspect("equal")


def draw_donuts(t: dict, out: Path, width: float = 4.2) -> None:
    plt = style.plt()
    fig, axes = plt.subplots(1, 3, figsize=(width, 1.8))
    d = t["deferred"]
    _donut(axes[0], [(d, ACCENT, 0.12), (t["eager"], EAGER_COLOR, 0)],
           f"{d / t['pairs']:.1%}",
           f"All module pairs\n{t['pairs']:,}",
           f"deferred-only {d:,}\neager-linked {t['eager']:,}")
    _donut(axes[1], [(t["in_function"], IN_FUNCTION_COLOR, 0), (t["type_only"], TYPE_ONLY_COLOR, 0)],
           f"{t['in_function'] / d:.1%}\nin-func.",
           f"Deferred-only pairs\n{d:,}, by kind",
           f"in-function {t['in_function']:,}\ntype-only {t['type_only']:,}")
    _donut(axes[2], [(t["closing"], ACCENT, 0), (t["not_closing"], ACCENT_LIGHT, 0)],
           f"{t['closing'] / d:.0%}",
           f"Deferred-only pairs\n{d:,}: close a cycle?",
           f"close a cycle {t['closing']:,}\ndo not {t['not_closing']:,}")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.97, bottom=0.42, wspace=0.3)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--share", type=Path, required=True, help="CSV from graphs --level file --csv")
    ap.add_argument("--cycles", type=Path, required=True, help="CSV from cycles --level file --csv")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig2-share.pdf"))
    a = ap.parse_args(argv)
    t = totals(a.share, a.cycles)
    d = t["deferred"]
    print(f"all pairs {t['pairs']:,}: deferred-only {d:,} ({d / t['pairs']:.1%}), "
          f"eager-linked {t['eager']:,} ({t['eager'] / t['pairs']:.1%})")
    print(f"deferred-only {d:,}: in-function {t['in_function']:,} ({t['in_function'] / d:.1%}), "
          f"type-only {t['type_only']:,} ({t['type_only'] / d:.1%})")
    print(f"deferred-only {d:,}: close a cycle {t['closing']:,} ({t['closing'] / d:.1%}), "
          f"do not {t['not_closing']:,} ({t['not_closing'] / d:.1%})")
    draw_donuts(t, a.out)


if __name__ == "__main__":
    main()
