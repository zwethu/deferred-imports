"""RQ1 hidden cycles: files that sit in an import cycle, without and with deferred imports.

One row per project: the open dot is the eager graph (top-level imports only), the filled dot
is the full graph (deferred imports included). Rows sorted by the full-graph count. A "0" on the
left means the project looks cycle-free to a top-level-only tool. Log scale (0 shown at 0).
Input: the CSV from
    uv run python -m deferred_imports.analysis.cycles index/*.sqlite --level file --csv cycles.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from deferred_imports.figures import style

EAGER_COLOR = "0.55"
FULL_COLOR = "#1f4e79"          # same blue as the in-function bars in fig5_km


def cycle_rows(cycles_csv: Path) -> list[dict]:
    """[{'repo', 'eager', 'full', 'largest_eager', 'largest_full'}], most files in cycles first."""
    with open(cycles_csv, newline="") as f:
        rows = [{"repo": r["repo"],
                 "eager": int(r["nodes_in_cycles_eager"]), "full": int(r["nodes_in_cycles_full"]),
                 "largest_eager": int(r["largest_scc_eager"]),
                 "largest_full": int(r["largest_scc_full"])} for r in csv.DictReader(f)]
    return sorted(rows, key=lambda r: (-r["full"], r["repo"].lower()))


def summary(rows: list[dict]) -> dict:
    """The numbers the text quotes."""
    return {"projects": len(rows),
            "files_in_cycles_eager": sum(r["eager"] for r in rows),
            "files_in_cycles_full": sum(r["full"] for r in rows),
            "cycle_free_eager_only": sorted(r["repo"] for r in rows if r["eager"] == 0 and r["full"] > 0),
            "largest_scc_grows": sum(r["largest_full"] > r["largest_eager"] for r in rows)}


def draw_hidden_cycles(rows: list[dict], out: Path, width: float = style.COLUMN) -> None:
    rows = sorted(rows, key=lambda r: (-r["largest_full"], r["repo"]))
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, 0.13 * len(rows) + 0.7))
    y = np.arange(len(rows))[::-1]
    eager = np.array([r["largest_eager"] for r in rows])
    full = np.array([r["largest_full"] for r in rows])
    for yy, a, b in zip(y, eager, full):
        ax.plot([a, b], [yy, yy], color="0.8", lw=1.2, zorder=1)
    ax.scatter(eager, y, s=14, facecolor="white", edgecolor=EAGER_COLOR, lw=0.9, zorder=2,
               label="Eager-only graph")
    ax.scatter(full, y, s=14, color=FULL_COLOR, zorder=3, label="With deferred imports")
    labels = [f"{r['repo']}*" if r["largest_eager"] == 0 and r["largest_full"] > 0 else r["repo"] for r in rows]
    ax.set_yticks(y, labels, fontsize=6.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(-0.3, max(full) * 1.6)
    ax.set_xticks([0, 1, 10, 100, 1000], ["0", "1", "10", "100", "1,000"])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel("Files in largest cyclic component (log scale)")
    ax.grid(axis="x", color="0.9", lw=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=2,
              handletextpad=0.3, columnspacing=1)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.text(0, -0.17, "* no cycle without deferred imports", transform=ax.transAxes,
            fontsize=6, va="top", ha="left", color="0.3")
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cycles", type=Path, required=True, help="CSV from cycles --level file --csv")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig-hidden-cycles.pdf"))
    a = ap.parse_args(argv)
    rows = cycle_rows(a.cycles)
    for r in rows:
        print(f"{r['repo']}: files in cycles {r['eager']} -> {r['full']}, "
              f"largest cycle {r['largest_eager']} -> {r['largest_full']}")
    s = summary(rows)
    print(f"all {s['projects']} projects: files in cycles {s['files_in_cycles_eager']} -> "
          f"{s['files_in_cycles_full']}; largest cycle grows in {s['largest_scc_grows']}; "
          f"look cycle-free without deferred imports ({len(s['cycle_free_eager_only'])}): "
          f"{', '.join(s['cycle_free_eager_only'])}")
    draw_hidden_cycles(rows, a.out)


if __name__ == "__main__":
    main()
