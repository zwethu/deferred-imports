"""RQ1 box plot: per-project share of file pairs that are deferred-only, by project group.

One box per group (well-known, less-known, AI-heavy) and one for all 24 projects. Whiskers
reach the furthest project within 1.5 x IQR. Every project is drawn as a dot on top, because
the groups are small (10, 10 and 4 projects). Dashed line: median of all projects.
Input: the CSV from
    uv run python -m deferred_imports.analysis.graphs index/*.sqlite --level file --csv share.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import median

from deferred_imports.figures import style
from deferred_imports.figures.table1_subjects import GROUPS


def group_shares(share_csv: Path) -> list[tuple[str, list[tuple[str, float]]]]:
    """[(label, [(repo, share in %)])] for each group in Table I order, then 'Overall'."""
    with open(share_csv, newline="") as f:
        share = {r["repo"]: 100 * float(r["share_deferred_only"]) for r in csv.DictReader(f)}
    out = []
    for _key, label, repos in GROUPS:
        missing = [r for r in repos if r not in share]
        if missing:
            raise SystemExit(f"{share_csv}: no row for {', '.join(missing)}")
        out.append((label, [(r, share[r]) for r in repos]))
    every = [p for _, g in out for p in g]
    out.append(("Overall", every))
    return out


def draw(groups, out: Path, width: float = style.COLUMN) -> None:
    import numpy as np

    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, width * 0.62))
    data = [[v for _, v in g] for _, g in groups]
    positions = list(range(1, len(groups) + 1))
    positions[-1] += 0.3
    boxes = ax.boxplot(
        data, positions=positions, whis=1.5, widths=0.5, showfliers=False, patch_artist=True,
        boxprops={"edgecolor": "black", "lw": 0.7},
        medianprops={"color": "black", "lw": 0.65},
        whiskerprops={"lw": 0.7}, capprops={"lw": 0.7},
    )
    # Google logo colors blended with white for legible dots and median lines.
    fills = {
        "Well-known": "#BDDEF9",
        "Less-known": "#F8C0BB",
        "AI-heavy": "#FEE7A6",
        "Overall": "#BBE1C7",
    }
    for box, (label, _) in zip(boxes["boxes"], groups, strict=True):
        box.set_facecolor(fills.get(label, "#E6E6E6"))
    rng = np.random.default_rng(1)                     # fixed jitter, same figure every run
    for k, (_, g) in zip(positions, groups, strict=True):
        xs = k + rng.uniform(-0.13, 0.13, len(g))
        ax.scatter(xs, [v for _, v in g], s=6, facecolors="#454545",
                   edgecolors="white", linewidths=0.3, zorder=3)
    overall = median(data[-1])
    ax.axhline(overall, color="black", ls="--", lw=0.6, zorder=1)
    label_x = (positions[-2] + positions[-1]) / 2
    ax.text(label_x, overall + 0.3, f"Overall median\n({overall:.1f}%)",
            va="bottom", ha="center", fontsize=6.5)
    ax.set_xlim(0.4, positions[-1] + 0.5)
    ax.set_xticks(positions)
    ax.set_xticklabels([f"{label}\n(n = {len(g)})" for label, g in groups])
    ax.set_ylabel("Deferred-only pairs (%)")
    ax.set_ylim(0, None)
    ax.spines[["top", "right"]].set_visible(False)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--share", type=Path, default=Path("out/figures/share.csv"))
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig-share-box.pdf"))
    a = ap.parse_args(argv)
    groups = group_shares(a.share)
    for label, g in groups:
        vals = [v for _, v in g]
        print(f"{label}: n={len(g)}, median={median(vals):.1f}%, "
              f"range={min(vals):.1f}%-{max(vals):.1f}%")
    draw(groups, a.out)


if __name__ == "__main__":
    main()
