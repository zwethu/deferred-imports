"""Show the change in each project's largest cyclic component."""

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style


def draw(cycles: Path, out: Path) -> None:
    with cycles.open(newline="") as source:
        rows = [
            (row["repo"], int(row["largest_scc_eager"]), int(row["largest_scc_full"]))
            for row in csv.DictReader(source)
        ]
    rows.sort(key=lambda row: (row[2] - row[1], row[0]))
    names, before, after = zip(*rows)
    gains = [end - start for start, end in zip(before, after, strict=True)]
    colors = ["#185ABC" if start == 0 and end > 0 else "#BDDEF9"
              for start, end in zip(before, after, strict=True)]

    plt = style.plt()
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(style.COLUMN, 4.2))
    y = range(len(rows))
    ax.barh(y, gains, color=colors, height=0.67)
    ax.set_yticks(y, names, fontsize=6.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(gains) * 1.16)
    ax.set_xlabel("Increase in largest cyclic component (files)")
    for i, gain in enumerate(gains):
        ax.annotate(f"+{gain}" if gain else "0", (gain, i), xytext=(3, 0),
                    textcoords="offset points", va="center", fontsize=6)
    ax.legend(handles=[Patch(facecolor="#185ABC", label="Cycles first appeared"),
                       Patch(facecolor="#BDDEF9", label="Already had cycles")],
              loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color="#e4e4e4", linewidth=0.5)
    ax.set_axisbelow(True)
    style.save(fig, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=Path, default=Path("data/e3_cycles.csv"))
    parser.add_argument("--out", type=Path, default=Path("out/figures/fig-cycle-gain.pdf"))
    args = parser.parse_args()
    draw(args.cycles, args.out)


if __name__ == "__main__":
    main()
