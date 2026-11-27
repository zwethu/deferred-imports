"""Compare the largest cyclic strongly connected component in each project."""

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style


def draw(cycles: Path, out: Path) -> None:
    with cycles.open(newline="") as source:
        rows = sorted(
            ((r["repo"], int(r["largest_scc_eager"]), int(r["largest_scc_full"]))
             for r in csv.DictReader(source)),
            key=lambda row: (row[2], row[0]),
        )
    names, eager, full = zip(*rows)
    y = range(len(rows))
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(style.COLUMN, 4.6))
    ax.hlines(y, eager, full, color="#888888", linewidth=0.75)
    ax.scatter(full, y, s=16, color="#185ABC", label="Full graph", zorder=3)
    ax.scatter(eager, y, s=10, facecolors="white", edgecolors="#222222",
               linewidths=0.65, label="Eager-only graph", zorder=4)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(-0.1, max(full) * 1.35)
    ticks = [v for v in (0, 1, 10, 100, 1000) if v <= max(full) * 1.35]
    ax.set_xticks(ticks, [str(v) for v in ticks])
    ax.set_yticks(y, names, fontsize=6.5)
    ax.set_xlabel("Files in largest cyclic SCC")
    ax.grid(axis="x", color="#dddddd", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False)
    style.save(fig, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=Path, default=Path("data/e3_cycles.csv"))
    parser.add_argument("--out", type=Path, default=Path("out/figures/fig-scc-change.pdf"))
    args = parser.parse_args()
    draw(args.cycles, args.out)


if __name__ == "__main__":
    main()
