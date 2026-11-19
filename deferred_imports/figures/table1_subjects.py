"""Table I: the 24 subject projects, made from the data files only.

Inputs:
    corpus/paper-corpus.csv      group, years, first-parent commits
    out/figures/share.csv        from `analysis.graphs index/*.sqlite --level file --csv`
    out/figures/cycles.csv       from `analysis.cycles index/*.sqlite --level file --csv`
Output: a LaTeX table (booktabs, table*, label tab:subjects).
    uv run python -m deferred_imports.figures.table1_subjects --out out/figures/table1-subjects.tex
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

GROUPS = [("well-known", "Well-known",
           ["django", "numpy", "saleor", "netbox", "celery", "scrapy", "pip", "poetry", "pylint",
            "certbot"]),
          ("less-known", "Less-known",
           ["relate", "opendrift", "oq-engine", "osf.io", "the-blue-alliance", "kpi",
            "Sefaria-Project", "archivematica", "landlab", "dipy"]),
          ("ai-heavy", "AI-heavy", ["lutris", "awx", "haystack", "kornia"])]

ARROW = r"\(\rightarrow\)"
FOOTNOTE = ("a: first-parent commits. Years: age of the repository. In-function: at least one "
            "in-function import; type-only: only TYPE\\_CHECKING imports. Share: deferred-only / "
            "pairs. Largest cycle: files in the largest strongly connected component, eager graph "
            f"{ARROW} full graph; in the All row, total files in a cycle, eager {ARROW} full.")


def _read(path: Path) -> dict:
    with open(path, newline="") as f:
        return {r.get("repo") or r["name"]: r for r in csv.DictReader(f)}


def table_rows(corpus_csv: Path, share_csv: Path, cycles_csv: Path) -> list[dict]:
    """One dict per project in paper order, then an 'All' dict. Fails if a project is missing."""
    corpus, share, cycles = _read(corpus_csv), _read(share_csv), _read(cycles_csv)
    rows = []
    for key, label, repos in GROUPS:
        for repo in repos:
            c, s, y = corpus[repo], share[repo], cycles[repo]
            if c["group"] != key:
                raise SystemExit(f"{repo}: group {c['group']!r} in corpus, {key!r} in Table I")
            deferred, type_only = int(s["pairs_deferred_only"]), int(s["pairs_type_only"])
            rows.append({"group": label, "repo": repo, "years": int(c["years"]),
                         "commits": int(c["first_parent_commits"]), "pairs": int(s["pairs"]),
                         "deferred": deferred, "in_function": deferred - type_only,
                         "type_only": type_only,
                         "cycle_eager": int(y["largest_scc_eager"]),
                         "cycle_full": int(y["largest_scc_full"]),
                         "files_cycle_eager": int(y["nodes_in_cycles_eager"]),
                         "files_cycle_full": int(y["nodes_in_cycles_full"])})
    total = {k: sum(r[k] for r in rows) for k in
             ("commits", "pairs", "deferred", "in_function", "type_only",
              "files_cycle_eager", "files_cycle_full")}
    return rows + [{"group": None, "repo": "All", "years": None, **total,
                    "cycle_eager": total["files_cycle_eager"], "cycle_full": total["files_cycle_full"]}]


def _n(v: int) -> str:
    return f"{v:,}"


def render(rows: list[dict]) -> str:
    out = [r"\begin{table*}[t]", r"\centering",
           r"\caption{Subject projects at the pinned commit (file level).}", r"\label{tab:subjects}",
           r"\begin{tabular}{lrrrrrrrc}", r"\toprule",
           (r"Project & Years & Commits\textsuperscript{a} & Pairs & Deferred-only & In-function"
            r" & Type-only & Share \% & Largest cycle (files) \\"), r"\midrule"]
    group = None
    for r in rows:
        if r["repo"] == "All":
            out.append(r"\midrule")
        elif r["group"] != group:
            group = r["group"]
            out.append(rf"\multicolumn{{9}}{{l}}{{\textit{{{group}}}}} \\")
        share = 100 * r["deferred"] / r["pairs"] if r["pairs"] else 0.0
        years = "" if r["years"] is None else str(r["years"])
        name = r"\textbf{All}" if r["repo"] == "All" else r["repo"]
        cyc = f"{_n(r['cycle_eager'])} {ARROW} {_n(r['cycle_full'])}"
        out.append(f"{name} & {years} & {_n(r['commits'])} & {_n(r['pairs'])} & {_n(r['deferred'])}"
                   f" & {_n(r['in_function'])} & {_n(r['type_only'])} & {share:.1f} & {cyc} \\\\")
    out += [r"\bottomrule", r"\end{tabular}",
            rf"\par\smallskip\footnotesize {FOOTNOTE}", r"\end{table*}", ""]
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=Path("corpus/paper-corpus.csv"))
    ap.add_argument("--share", type=Path, default=Path("out/figures/share.csv"))
    ap.add_argument("--cycles", type=Path, default=Path("out/figures/cycles.csv"))
    ap.add_argument("--out", type=Path, default=Path("out/figures/table1-subjects.tex"))
    a = ap.parse_args(argv)
    rows = table_rows(a.corpus, a.share, a.cycles)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render(rows))
    al = rows[-1]
    print(f"All: commits {al['commits']:,}, pairs {al['pairs']:,}, deferred-only {al['deferred']:,}, "
          f"in-function {al['in_function']:,}, type-only {al['type_only']:,}, "
          f"share {100 * al['deferred'] / al['pairs']:.1f}%, files in cycles "
          f"{al['cycle_eager']:,} -> {al['cycle_full']:,}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
