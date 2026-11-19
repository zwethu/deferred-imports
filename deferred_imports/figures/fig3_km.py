"""Fig. 3 (RQ2): how long a pair stays deferred-only, as bars at 1, 2 and 5 years.

Kaplan-Meier estimates for in-function and type-only pairs, first episodes only, calendar
time, 95% Greenwood (log-log) bands as error bars.
Input: the databases (slow) or the episodes CSV from `fate --episodes`.
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from pathlib import Path

import numpy as np

from deferred_imports.analysis.fate import episodes, kaplan_meier, km_median
from deferred_imports.figures import style


def greenwood_band(times, events, z: float = 1.96):
    """KM curve with a 95% band (Greenwood variance, log-log transform), as step data."""
    t, e = np.asarray(times, float), np.asarray(events, int)
    ut, s = kaplan_meier(t, e)
    var_sum, lo, hi = 0.0, [], []
    for u, sv in zip(ut, s):
        n_risk = np.sum(t >= u)
        d = np.sum((t == u) & (e == 1))
        if n_risk > d:
            var_sum += d / (n_risk * (n_risk - d))
        if 0 < sv < 1:
            se = math.sqrt(var_sum) / abs(math.log(sv))
            lo.append(sv ** math.exp(z * se))
            hi.append(sv ** math.exp(-z * se))
        else:
            lo.append(sv)
            hi.append(sv)
    return ut, s, np.array(lo), np.array(hi)


def first_episodes(inputs: list[Path]) -> list[dict]:
    """[{'repo', 'type_only', 'days', 'outcome'}] for first episodes, from DBs or a CSV."""
    rows = []
    for p in inputs:
        if p.suffix == ".csv":
            with open(p, newline="") as f:
                for r in csv.DictReader(f):
                    if int(r["episode"]) == 1:
                        rows.append({"repo": r["repo"], "type_only": r["type_only"] in ("1", "True"),
                                     "days": float(r["days"]), "outcome": r["outcome"]})
        else:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            for e in episodes(con, "file"):
                if e["episode"] == 1:
                    rows.append({"repo": p.stem, "type_only": bool(e["type_only"]),
                                 "days": float(e["days"]), "outcome": e["outcome"]})
    return rows


def km_groups(rows: list[dict]) -> dict:
    """{'In-function': (times, events), 'Type-only': (...)}."""
    out = {}
    for name, flag in (("In-function", False), ("Type-only", True)):
        g = [r for r in rows if r["type_only"] == flag]
        out[name] = ([r["days"] for r in g], [int(r["outcome"] != "kept") for r in g])
    return out


KM_STYLE = {"In-function": {"color": "#1f4e79", "ls": "-"},
            "Type-only": {"color": "#d95f02", "ls": "--"}}


YEARS = (1, 2, 5)


def km_at(times, events, years=YEARS) -> list[tuple[float, float, float]]:
    """Kaplan-Meier share still deferred-only at each year, with its 95% band: [(s, lo, hi)]."""
    ut, s, lo, hi = greenwood_band(times, events)
    out = []
    for y in years:
        k = np.searchsorted(ut, y * 365.25, side="right") - 1
        out.append((1.0, 1.0, 1.0) if k < 0 else (float(s[k]), float(lo[k]), float(hi[k])))
    return out


def draw_bars(groups: dict, out: Path, width: float = style.COLUMN, years=YEARS) -> None:
    """Grouped bars: % of pairs still deferred-only after 1, 2 and 5 years, with 95% bands."""
    plt = style.plt()
    fig, ax = plt.subplots(figsize=(width, width * 0.55))
    w = 0.36
    for k, (name, (t, e)) in enumerate(groups.items()):
        vals = km_at(t, e, years)
        xs = np.arange(len(years)) + (k - 0.5) * w
        v = np.array([a for a, _, _ in vals])
        err = np.array([[a - lo for a, lo, _ in vals], [hi - a for a, _, hi in vals]])
        ax.bar(xs, v, w, color=KM_STYLE[name]["color"], label=f"{name} (n = {len(t):,})",
               yerr=err, error_kw={"lw": 0.7, "capsize": 2, "ecolor": "black"})
        for x, a, (_, _, hi) in zip(xs, v, vals):
            ax.text(x, hi + 0.02, f"{a:.0%}", ha="center", fontsize=6.5)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([f"after {y} year{'s' if y > 1 else ''}" for y in years])
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("% of pairs still deferred-only")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.15))
    ax.spines[["top", "right"]].set_visible(False)
    style.save(fig, out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", type=Path, help="index/*.sqlite or an episodes CSV")
    ap.add_argument("--out", type=Path, default=Path("out/figures/fig3-km.pdf"))
    a = ap.parse_args(argv)
    groups = km_groups(first_episodes(a.inputs))
    for name, (t, e) in groups.items():
        med = km_median(t, e) if t else None
        kept = (len(e) - sum(e)) / len(e) if e else 0
        print(f"{name}: n={len(t)}, median days={med if med is None else round(med)}, "
              f"kept={kept:.1%}")
        for y, (v, lo, hi) in zip(YEARS, km_at(t, e)):
            print(f"  after {y} year(s): {v:.1%} (95% CI {lo:.1%}-{hi:.1%})")
    draw_bars(groups, a.out)


if __name__ == "__main__":
    main()
