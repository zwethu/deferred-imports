import csv

from deferred_imports.figures.fig2_cycle import link_label
from deferred_imports.figures.fig3_km import greenwood_band
from deferred_imports.figures.fig4_fates import fate_rows


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_fate_rows_split_and_total(tmp_path):
    write(tmp_path / "fate.csv", [
        {"repo": "a", "promoted": 4, "removed": 3, "kept": 3},
        {"repo": "b", "promoted": 0, "removed": 1, "kept": 9}])
    write(tmp_path / "kinds.csv", [
        {"repo": "a", "same_name_left": 1, "different_name_left": 1},
        {"repo": "ALL", "same_name_left": 1, "different_name_left": 1}])
    rows = fate_rows(tmp_path / "fate.csv", tmp_path / "kinds.csv")
    assert [r["repo"] for r in rows] == ["a", "b", "All"]          # sorted by share promoted
    assert rows[0]["promoted_clean"] == 2
    assert rows[0]["promoted_dead"] == 1 and rows[0]["promoted_other"] == 1
    assert rows[-1] == {"repo": "All", "promoted_clean": 2, "promoted_dead": 1,
                        "promoted_other": 1, "removed": 4, "kept": 12, "n": 20}


def test_greenwood_band_contains_curve():
    t, s, lo, hi = greenwood_band([1, 2, 2, 3, 5, 8], [1, 1, 0, 1, 0, 1])
    assert list(t) == [1, 2, 3, 8]
    assert all(l <= v <= h for l, v, h in zip(lo, s, hi))


def test_link_label():
    assert link_label(["top_level", "in_function"]) == ""
    assert link_label(["type_checking"]) == "TYPE_CHECKING"
    assert link_label(["in_function", "type_checking"]) == "in-function"


def test_bootstrap_ci_brackets_estimate():
    import numpy as np

    from deferred_imports.analysis.bootstrap import bootstrap_ci
    vals = [0.01, 0.02, 0.05, 0.1, 0.3]
    est, lo, hi = bootstrap_ci(vals, np.mean, resamples=2000, seed=1)
    assert lo <= est <= hi and abs(est - 0.096) < 1e-9
    assert bootstrap_ci(vals, np.mean, 2000, 1) == (est, lo, hi)      # fixed seed: same result


def test_km_at_steps_and_band():
    from deferred_imports.figures.fig3_km import km_at
    t = [100, 200, 400, 800, 900, 2000]
    e = [1, 0, 1, 1, 0, 0]
    (s1, _lo1, _hi1), (s2, lo2, hi2) = km_at(t, e, years=(0.1, 1.5))
    assert s1 == 1.0                       # no event before 36 days
    assert lo2 <= s2 <= hi2 and s2 < 1


def test_hidden_cycles_summary(tmp_path):
    from deferred_imports.figures.fig_hidden_cycles import cycle_rows, summary
    cols = ["repo", "nodes_in_cycles_eager", "nodes_in_cycles_full",
            "largest_scc_eager", "largest_scc_full"]
    write(tmp_path / "c.csv", [dict(zip(cols, v)) for v in
                               (["a", 0, 10, 0, 10], ["b", 5, 5, 5, 5], ["c", 2, 30, 2, 20])])
    rows = cycle_rows(tmp_path / "c.csv")
    assert [r["repo"] for r in rows] == ["c", "a", "b"]
    s = summary(rows)
    assert s["files_in_cycles_eager"] == 7 and s["files_in_cycles_full"] == 45
    assert s["cycle_free_eager_only"] == ["a"] and s["largest_scc_grows"] == 2


def test_table1_rows_and_render(tmp_path):
    from deferred_imports.figures import table1_subjects as t1
    repos = [r for _, _, rs in t1.GROUPS for r in rs]
    group = {r: k for k, _, rs in t1.GROUPS for r in rs}
    write(tmp_path / "corpus.csv", [{"name": r, "group": group[r], "years": 10,
                                     "first_parent_commits": 100} for r in repos])
    write(tmp_path / "share.csv", [{"repo": r, "pairs": 50, "pairs_deferred_only": 5,
                                    "pairs_type_only": 2} for r in repos])
    write(tmp_path / "cycles.csv", [{"repo": r, "largest_scc_eager": 0, "largest_scc_full": 3,
                                     "nodes_in_cycles_eager": 1, "nodes_in_cycles_full": 4}
                                    for r in repos])
    rows = t1.table_rows(tmp_path / "corpus.csv", tmp_path / "share.csv", tmp_path / "cycles.csv")
    assert [r["repo"] for r in rows[:-1]] == repos and rows[-1]["repo"] == "All"
    assert rows[0]["in_function"] == 3
    assert rows[-1]["pairs"] == 50 * 24 and rows[-1]["cycle_full"] == 4 * 24
    tex = t1.render(rows)
    assert r"\label{tab:subjects}" in tex and "10.0" in tex and r"\textbf{All}" in tex
