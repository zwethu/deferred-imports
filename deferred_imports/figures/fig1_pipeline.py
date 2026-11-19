"""Fig. 1: the mining and analysis process (boxes and arrows)."""

from __future__ import annotations

import argparse
from pathlib import Path

from deferred_imports.figures import style

# (key, x centre, y centre, width, height, title, body lines, dashed)
PIPELINE_BOXES = [
    ("repos", 5.0, 11.2, 6.0, 1.0, "24 Python projects", ["git history, pinned commit"], False),
    ("miner", 5.0, 9.25, 8.4, 2.1, "Miner (per first-parent commit)",
     ["1. parse changed .py files (tree-sitter)",
      "2. tag each import: module-level, try/except,", "in-function, TYPE_CHECKING",
      "3. resolve imports to project files"], False),
    ("log", 3.75, 7.05, 4.3, 1.0, "Import edge log", ["SQLite, one per project"], False),
    ("verify", 8.35, 7.05, 3.1, 1.0, "Verifier", ["git + Python ast"], True),
    ("share", 1.55, 4.95, 2.9, 1.6, "Count", ["deferred-only", "pairs at HEAD", "RQ1"], False),
    ("cycles", 5.0, 4.95, 2.9, 1.6, "Cycles", ["SCCs, eager vs", "full graph", "RQ1"], False),
    ("fate", 8.45, 4.95, 2.9, 1.6, "Fate", ["episodes,", "Kaplan–Meier", "RQ2"], False),
    ("check", 5.0, 2.75, 6.0, 1.3, "Manual check (3 authors)",
     ["60 cycle links + 60 promotions", "each import line read by hand"], False),
]
# (from, to, from side, to side, dashed); sides: t/b/l/r
PIPELINE_ARROWS = [("repos", "miner", "b", "t", False), ("miner", "log", "b", "t", False),
                   ("verify", "log", "l", "r", True), ("log", "share", "b", "t", False),
                   ("log", "cycles", "b", "t", False), ("log", "fate", "b", "t", False),
                   ("cycles", "check", "b", "t", False), ("fate", "check", "b", "t", False)]


def draw_pipeline(out: Path, width: float = style.COLUMN) -> None:
    """Fig. 1, the mining and analysis process, drawn from PIPELINE_BOXES/ARROWS."""
    from matplotlib.patches import FancyBboxPatch
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, width * 1.12))
    ax.set_xlim(0, 10)
    ax.set_ylim(1.9, 11.9)
    ax.axis("off")
    box = {}
    for key, x, y, w, h, title, body, dashed in PIPELINE_BOXES:
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                    boxstyle="round,pad=0,rounding_size=0.12", fc="white",
                                    ec="black", lw=0.8, ls=(0, (3, 2)) if dashed else "-"))
        lines = [title, *body]
        gap = 0.4
        for i, line in enumerate(lines):
            ax.text(x, y + gap * ((len(lines) - 1) / 2 - i), line, ha="center", va="center",
                    fontsize=6.5, fontweight="bold" if i == 0 else "normal",
                    style="italic" if line.startswith("RQ") else "normal")
        box[key] = (x, y, w, h)

    def side(k, sd, toward=None):
        x, y, w, h = box[k]
        if sd in "tb":
            px = x if toward is None else min(max(toward, x - w / 2 + 0.3), x + w / 2 - 0.3)
            return (px, y + h / 2 if sd == "t" else y - h / 2)
        return (x - w / 2 if sd == "l" else x + w / 2, y)

    for a, b, sa, sb, dashed in PIPELINE_ARROWS:
        end = side(b, sb)
        start = side(a, sa, toward=end[0] if sa in "tb" else None)
        if sa == "b" and sb == "t" and abs(start[0] - end[0]) > 0.05 and a != "log":
            end = side(b, sb, toward=start[0])          # straight down when boxes overlap
        ax.annotate("", xy=end, xytext=start,
                    arrowprops={"arrowstyle": "-|>", "mutation_scale": 8, "lw": 0.8,
                                "color": "black", "linestyle": (0, (3, 2)) if dashed else "-",
                                "shrinkA": 0, "shrinkB": 0})
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig1-pipeline.pdf"))
    draw_pipeline(ap.parse_args(argv).out)


if __name__ == "__main__":
    main()
