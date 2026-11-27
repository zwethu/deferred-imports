"""Summarize how adding deferred imports changed cycles across projects."""

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style


def draw(cycles: Path, out: Path) -> None:
    with cycles.open(newline="") as source:
        rows = list(csv.DictReader(source))

    first = sum(int(r["sccs_eager"]) == 0 and int(r["sccs_full"]) > 0 for r in rows)
    larger = sum(int(r["largest_scc_full"]) > int(r["largest_scc_eager"]) for r in rows)
    counts = (first, larger - first, len(rows) - larger)
    labels = ("First cycles appeared", "Existing cyclic component grew", "No increase")
    colors = ("#185ABC", "#BDDEF9", "#ECEEF0")

    plt = style.plt()
    fig = plt.figure(figsize=(style.COLUMN, 2.0))
    fig.text(0.04, 0.87, f"{larger} of {len(rows)} projects", fontsize=17,
             weight="bold", color="#185ABC")
    fig.text(0.04, 0.70, "had a larger cyclic component after adding deferred imports",
             fontsize=7.6)

    ax = fig.add_axes((0.04, 0.50, 0.92, 0.125))
    left = 0
    for count, color, ink in zip(counts, colors, ("white", "#17212D", "#17212D"), strict=True):
        ax.barh(0, count, left=left, height=1, color=color, edgecolor="white", linewidth=1)
        if count:
            ax.text(left + count / 2, 0, str(count), ha="center", va="center",
                    color=ink, fontsize=9, weight="bold")
        left += count
    ax.set(xlim=(0, len(rows)), ylim=(-0.5, 0.5))
    ax.set_axis_off()

    for i, (label, color) in enumerate(zip(labels, colors, strict=True)):
        y = 0.40 - 0.082 * i
        fig.text(0.04, y, "■", color=color, fontsize=9, va="center")
        fig.text(0.095, y, label, fontsize=8, va="center")

    saleor = next((r for r in rows if r["repo"].lower() == "saleor"), None)
    if saleor:
        before = int(saleor["largest_scc_eager"])
        after = int(saleor["largest_scc_full"])
        fig.text(0.04, 0.095, f"Saleor: {before:,} → {after:,} files in its largest cyclic component",
                 fontsize=7.6)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=Path, default=Path("data/e3_cycles.csv"))
    parser.add_argument("--out", type=Path, default=Path("out/figures/fig-cycle-summary.pdf"))
    args = parser.parse_args()
    draw(args.cycles, args.out)


if __name__ == "__main__":
    main()
