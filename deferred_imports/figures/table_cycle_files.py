"""Render a table of the largest cyclic component in each project."""

import argparse
import csv
from pathlib import Path

from deferred_imports.figures import style


TITLE = "Largest mutually reachable group (files)"
HEADERS = ("Project", "Eager-only", "Full graph", "Change")


def table_rows(path: Path) -> list[tuple[str, int, int]]:
    with path.open(newline="", encoding="utf-8") as source:
        rows = [
            (
                row["repo"],
                int(row["largest_scc_eager"]),
                int(row["largest_scc_full"]),
            )
            for row in csv.DictReader(source)
        ]
    return sorted(rows, key=lambda row: (row[1] - row[2], row[0]))


def format_row(project: str, eager: int, full: int) -> tuple[str, ...]:
    change = full - eager
    return (project, f"{eager:,}" if eager else "No cycle",
            f"{full:,}" if full else "No cycle", f"{change:+,}" if change else "0")


def render_table(path: Path) -> str:
    lines = [
        f"**{TITLE}**",
        "",
        "| Project | Eager-only graph | Full graph | Change |",
        "|---|---:|---:|---:|",
    ]
    for project, eager, full in table_rows(path):
        cells = format_row(project, eager, full)
        if eager == 0 and full > 0:
            cells = tuple(f"**{cell}**" for cell in cells)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def save_table(path: Path, out: Path) -> None:
    rows = table_rows(path)
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(style.COLUMN, 0.24 + 0.155 * len(rows)))
    ax.set_axis_off()
    ax.set_title(TITLE, loc="left", pad=5, fontweight="bold")
    cells = [format_row(*row) for row in rows]
    table = ax.table(cellText=cells, colLabels=HEADERS, cellLoc="right",
                     colWidths=(0.43, 0.19, 0.20, 0.18), bbox=(0, 0, 1, 1))
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    for (row, column), cell in table.get_celld().items():
        cell.PAD = 0.05
        cell.set_linewidth(0.6)
        cell.visible_edges = "TB" if row == 0 else "B" if row == len(rows) else ""
        cell.get_text().set_ha("left" if column == 0 else "right")
        if row == 0 or rows[row - 1][1] == 0 < rows[row - 1][2]:
            cell.get_text().set_weight("bold")
    fig.subplots_adjust(left=0.025, right=0.975, top=0.94, bottom=0.02)
    style.save(fig, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycles", nargs="?", type=Path, default=Path("data/e3_cycles.csv"),
                        help="cycle results CSV (default: %(default)s)")
    parser.add_argument("--out", type=Path, help="save as an image or PDF")
    args = parser.parse_args()
    if args.out:
        save_table(args.cycles, args.out)
    else:
        print(render_table(args.cycles))


if __name__ == "__main__":
    main()
