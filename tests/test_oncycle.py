from deferred_imports.analysis.oncycle import comp_index, group_summary, on_cycle


def test_on_cycle_needs_way_back():
    comp = comp_index([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])
    assert on_cycle(comp, "a", "b") and on_cycle(comp, "c", "a")
    assert not on_cycle(comp, "c", "d")          # d cannot reach c again
    assert not on_cycle(comp, "x", "y")          # files not in any cycle


def test_group_summary_shares_and_skips_unknown():
    rows = [{"episode": 1, "type_only": False, "on_cycle_start": True, "outcome": o, "days": d}
            for o, d in (("promoted", 10), ("removed", 20), ("kept", 30), ("kept", 40))]
    rows.append({"episode": 1, "type_only": False, "on_cycle_start": None, "outcome": "removed",
                 "days": 5})                     # pair not in the graph: left out
    rows.append({"episode": 2, "type_only": False, "on_cycle_start": False, "outcome": "removed",
                 "days": 5})                     # not a first episode: left out
    s = group_summary(rows)
    assert [(r["kind"], r["episodes"]) for r in s] == [("in-function", 4), ("all", 4)]
    assert s[0]["promoted_pct"] == 25.0 and s[0]["kept_pct"] == 50.0
