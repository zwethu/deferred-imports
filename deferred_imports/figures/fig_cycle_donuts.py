"""RQ2: project-level cycle changes and deferred-only pairs that close cycles."""

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style


def cycle_counts(path: Path) -> tuple[tuple[int, int], tuple[int, int]]:
    """Count disjoint project outcomes and partition the deferred-only pairs."""
    full_only = project_count = closing = deferred = 0
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            project_count += 1
            if not int(row["sccs_eager"]) and int(row["sccs_full"]):
                full_only += 1
            closing += int(row["deferred_only_closing_cycle"])
            deferred += int(row["deferred_only_pairs"])
    return (full_only, project_count - full_only), (closing, deferred - closing)


def draw(cycles: Path, out: Path) -> None:
    projects, pairs = cycle_counts(cycles)
    plt = style.plt()
    fig, axes = plt.subplots(1, 2, figsize=(style.COLUMN, 2.15))
    fig.subplots_adjust(left=0.015, right=0.985, top=0.87, bottom=0.30, wspace=0.12)
    blue, red = "#BDDEF9", "#F8C0BB"
    panels = (
        ("Projects", projects, ("Cycle only in full graph", "Other projects"), (blue, red)),
        ("Deferred-only pairs", pairs, ("Close a cycle", "Do not close a cycle"),
         (blue, red)),
    )
    for ax, (title, counts, labels, colors) in zip(axes, panels, strict=True):
        total = sum(counts)
        wedges, _ = ax.pie(counts, colors=colors, startangle=90, counterclock=False,
                           wedgeprops={"width": 0.37, "edgecolor": "#333333",
                                       "linewidth": 0.55})
        ax.set_title(title, pad=3)
        ax.text(0, 0, f"{total:,}", ha="center", va="center", fontsize=10)
        entries = [
            f"{label}  {count:,}" if title == "Projects"
            else f"{label}  {count:,} ({count / total:.0%})"
            for label, count in zip(labels, counts, strict=True)
        ]
        ax.legend(wedges, entries, loc="upper center", bbox_to_anchor=(0.5, 0.0),
                  frameon=False, fontsize=6.5, handlelength=0.85, handletextpad=0.45)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=Path, default=Path("data/e3_cycles.csv"))
    parser.add_argument("--out", type=Path, default=Path("out/figures/fig-cycle-donuts.pdf"))
    args = parser.parse_args()
    draw(args.cycles, args.out)


if __name__ == "__main__":
    main()
