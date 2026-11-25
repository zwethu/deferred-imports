from deferred_imports.figures.table2_fates import render, table_rows, to_latex


def test_table_rows_shares_by_kind():
    rows = ([{"type_only": False, "outcome": o} for o in ("promoted", "removed", "removed", "kept")]
            + [{"type_only": True, "outcome": "kept"}])
    t = table_rows(rows)
    assert [r["kind"] for r in t] == ["In-function", "Type-only", "All"]
    assert t[0] == {"kind": "In-function", "episodes": 4, "promoted": 25.0, "removed": 50.0,
                    "kept": 25.0}
    assert t[1]["kept"] == 100.0 and t[2]["episodes"] == 5
    assert "Still deferred (%)" in render(t)
    assert r"\label{tab:fates}" in to_latex(t) and r"In-function & 4 & 25.0 & 50.0 & 25.0 \\" in to_latex(t)
