"""Fig. 3 (RQ1): one cycle that exists only through a deferred import.

Takes a deferred-only pair src -> dst at the last mined commit, finds the way back
dst -> ... -> src (eager imports first, else the full graph) and draws the cycle.
Dashed = deferred link.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sqlite3
from pathlib import Path

import numpy as np

from deferred_imports.analysis.cycles import shortest_path
from deferred_imports.analysis.graphs import is_deferred, pair_weights, split_pairs
from deferred_imports.figures import style


def file_ids(con: sqlite3.Connection) -> dict:
    """{path: file_id} for files that exist at the last commit."""
    return {p: f for f, p in con.execute("SELECT file_id, path FROM file_paths WHERE to_i IS NULL")}


def link_label(kinds) -> str:
    """'in-function', 'TYPE_CHECKING' or '' (eager) for one pair's import kinds."""
    if any(not is_deferred(k) for k in kinds):
        return ""
    return "TYPE_CHECKING" if all("type_checking" in k for k in kinds) else "in-function"


def find_cycle(db: Path, src: str, dst: str) -> list[tuple[str, str, str]]:
    """[(from_path, to_path, label), ...] around the cycle, starting with src -> dst."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ids = file_ids(con)
    path_of = {f: p for p, f in ids.items()}
    for p in (src, dst):
        if p not in ids:
            raise SystemExit(f"{p}: not a file at the last mined commit")
    w = pair_weights(con, "file")
    _, dfo = split_pairs(w)
    a, b = ids[src], ids[dst]
    if (a, b) not in dfo:
        raise SystemExit(f"{src} -> {dst} is not a deferred-only pair at the last commit")
    # Prefer a way back made only of eager imports: then the deferred link is the only thing
    # that closes the cycle. Fall back to the full graph (the paper's definition).
    eager, _ = split_pairs(w)
    back = shortest_path(list(eager), b, a) or shortest_path(list(w), b, a)
    if back is None:
        raise SystemExit(f"{src} -> {dst} does not close a cycle")
    nodes = [a] + back                                  # a, b, ..., a
    return [(path_of[x], path_of[y], link_label(w[(x, y)])) for x, y in itertools.pairwise(nodes)]


def draw_cycle(links, out: Path, strip: str = "", width: float = style.COLUMN) -> None:
    plt = style.plt()
    names = [a for a, _, _ in links]
    n = len(names)
    # drop the common prefix, but never down to a bare "__init__.py"
    short = [s[len(strip):] if strip and s.startswith(strip) and s[len(strip):] != "__init__.py"
             else s for s in names]
    # nodes on a circle, first node at the top, going clockwise
    pos = [(math.sin(2 * math.pi * k / n), math.cos(2 * math.pi * k / n)) for k in range(n)]
    fig, ax = plt.subplots(figsize=(width, width * 0.62))
    ax.set_xlim(-1.75, 1.75)
    ax.set_ylim(-1.35, 1.35)
    ax.axis("off")
    boxes = []
    for (x, y), label in zip(pos, short):
        t = ax.text(x, y, label, ha="center", va="center", family="monospace", fontsize=7,
                    bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "black", "lw": 0.8})
        boxes.append(t)
    fig.canvas.draw()
    for k, (_, _, label) in enumerate(links):
        p, q = pos[k], pos[(k + 1) % n]
        ax.annotate("", xy=q, xytext=p,
                    arrowprops={"arrowstyle": "-|>", "mutation_scale": 9, "lw": 0.9, "color": "black",
                                    "linestyle": (0, (4, 2.5)) if label else "-",
                                    "patchA": boxes[k].get_bbox_patch(),
                                    "patchB": boxes[(k + 1) % n].get_bbox_patch(),
                                    "shrinkA": 1, "shrinkB": 1})
        if label:
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            if abs(q[1] - p[1]) < 0.3:                  # flat link: label below the line
                ax.text(mx, my - 0.14, label, fontsize=7, style="italic", ha="center", va="top")
            else:
                ax.text(mx + 0.08 * np.sign(mx or 1), my + 0.06, label, fontsize=7,
                        style="italic", ha="left" if mx >= 0 else "right", va="center")
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db", type=Path)
    ap.add_argument("--src", required=True, help="path of the importing file")
    ap.add_argument("--dst", required=True, help="path of the imported file")
    ap.add_argument("--strip", default="", help="prefix to drop from the shown paths")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig3-cycle.pdf"))
    a = ap.parse_args(argv)
    links = find_cycle(a.db, a.src, a.dst)
    for x, y, label in links:
        print(f"{x} -> {y}  {label or 'eager'}")
    draw_cycle(links, a.out, a.strip)


if __name__ == "__main__":
    main()
