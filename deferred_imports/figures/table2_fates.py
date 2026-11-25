"""Table II (RQ3): outcome of the first episodes, in percent, by kind. Prints it in the terminal.

    uv run python -m deferred_imports.figures.table2_fates data/e2_episodes.csv
    uv run python -m deferred_imports.figures.table2_fates index/*.sqlite --out table2-fates.tex

Input: the episodes CSV from `analysis.fate --episodes` (or the mined databases). Only the
first episode of each file pair counts. Kinds: in-function (at least one in-function import)
and type-only (only TYPE_CHECKING imports). "Still deferred" = not ended at the last commit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from deferred_imports.figures.fig5_km import first_episodes

OUTCOMES = (("promoted", "Promoted (%)"), ("removed", "Removed (%)"), ("kept", "Still deferred (%)"))


def table_rows(rows: list[dict]) -> list[dict]:
    """[{'kind', 'episodes', 'promoted', 'removed', 'kept'}] with shares in percent."""
    out = []
    for kind, flag in (("In-function", False), ("Type-only", True), ("All", None)):
        g = [r for r in rows if flag is None or r["type_only"] == flag]
        n = len(g)
        out.append({"kind": kind, "episodes": n,
                    **{o: round(100 * sum(r["outcome"] == o for r in g) / n, 1) if n else 0.0
                       for o, _ in OUTCOMES}})
    return out


def render(rows: list[dict]) -> str:
    head = ["Kind", "Episodes"] + [label for _, label in OUTCOMES]
    body = [[r["kind"], f"{r['episodes']:,}"] + [f"{r[o]:.1f}" for o, _ in OUTCOMES] for r in rows]
    width = [max(len(x) for x in col) for col in zip(head, *body)]
    line = lambda cells: "  ".join(c.ljust(w) if k == 0 else c.rjust(w)
                                   for k, (c, w) in enumerate(zip(cells, width)))
    rule = "-" * len(line(head))
    return "\n".join(["TABLE II. Outcome of the first episodes, in percent.", rule, line(head),
                      rule, *map(line, body), rule])


def to_latex(rows: list[dict]) -> str:
    """The same table for the paper (needs \\usepackage{booktabs})."""
    head = " & ".join(["Kind", "Episodes"] + [label.replace("%", r"\%") for _, label in OUTCOMES])
    lines = [r"% Table II, made by deferred_imports/figures/table2_fates.py",
             r"\begin{table}[t]", r"\centering",
             r"\caption{Outcome of the first episodes, in percent.}", r"\label{tab:fates}",
             r"\begin{tabular}{lrrrr}", r"\toprule", head + r" \\", r"\midrule"]
    for r in rows:
        if r["kind"] == "All":
            lines.append(r"\midrule")
        lines.append(" & ".join([r["kind"], f"{r['episodes']:,}"]
                                + [f"{r[o]:.1f}" for o, _ in OUTCOMES]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", type=Path, help="episodes CSV or index/*.sqlite")
    ap.add_argument("--out", type=Path, help="also write the LaTeX table here")
    a = ap.parse_args(argv)
    rows = table_rows(first_episodes(a.inputs))
    print(render(rows))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(to_latex(rows))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
