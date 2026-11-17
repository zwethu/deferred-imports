import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from deferred_imports.analysis.fate import aalen_johansen, episodes, kaplan_meier, km_median, state

SCHEMA = Path(__file__).parent.parent / "deferred_imports" / "mining" / "schema.sql"


def test_state():
    assert state(Counter()) == "none"
    assert state(Counter({"in_function": 1})) == "deferred"
    assert state(Counter({"in_function": 1, "top_level": 1})) == "eager"
    assert state(Counter({"try_except": 1})) == "eager"
    assert state(Counter({"top_level": 0, "type_checking": 2})) == "deferred"


def test_km_and_aj():
    # 4 pairs: leave at 1 (promoted), 2 (removed), 3 (promoted); one kept until 4
    t, c = [1, 2, 3, 4], ["promoted", "removed", "promoted", 0]
    ut, s = kaplan_meier(t, [1, 1, 1, 0])
    assert list(ut) == [1, 2, 3] and s == pytest.approx([0.75, 0.5, 0.25])
    assert km_median(t, [1, 1, 1, 0]) == 2
    _, p = aalen_johansen(t, c, "promoted")
    _, r = aalen_johansen(t, c, "removed")
    assert p[-1] == pytest.approx(0.5) and r[-1] == pytest.approx(0.25)
    assert p[-1] + r[-1] == pytest.approx(1 - s[-1])   # the two add up to 1 - KM


def make_db(edges):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text())
    for i in range(6):
        con.execute("INSERT INTO commits VALUES (?,?,?,?,1,1,0,0,NULL,0,NULL,0,0)",
                    (i, f"s{i}", f"2026-01-0{i + 1}T00:00:00+00:00", "h"))
    con.execute("INSERT INTO modules VALUES (1,'a',0,NULL,NULL),(2,'b',0,NULL,NULL),"
                "(3,'c',0,NULL,NULL),(4,'tests',0,NULL,'tests')")
    con.executemany("INSERT INTO module_edges VALUES (?,?,?,?,?,'import')", edges)
    return con


def test_episodes_package():
    con = make_db([
        (1, 1, 2, 1, "in_function"),                                   # a->b deferred
        (3, 1, 2, 1, "top_level"),                                     # ... promoted (new)
        (1, 2, 3, 1, "type_checking"),                                 # b->c deferred
        (2, 2, 3, -1, "type_checking"),                                # ... removed
        (4, 2, 3, 1, "in_function"),                                   # b->c again: episode 2
        (2, 3, 1, 1, "in_function"),                                   # c->a deferred
        (5, 3, 1, -1, "in_function"), (5, 3, 1, 1, "top_level"),       # ... hoisted
        (1, 1, 4, 1, "in_function"),                                   # into tests: ignored
    ])
    got = {(e["src"], e["dst"], e["episode"]): e for e in episodes(con, "package")}
    assert set(got) == {(1, 2, 1), (2, 3, 1), (2, 3, 2), (3, 1, 1)}
    assert got[(1, 2, 1)]["outcome"] == "promoted" and got[(1, 2, 1)]["hoisted"] == 0
    assert got[(1, 2, 1)]["commits"] == 2 and got[(1, 2, 1)]["days"] == 2
    assert got[(2, 3, 1)]["outcome"] == "removed" and got[(2, 3, 1)]["type_only"]
    assert got[(2, 3, 2)]["outcome"] == "kept" and got[(2, 3, 2)]["end_i"] == 5
    assert got[(3, 1, 1)]["outcome"] == "promoted" and got[(3, 1, 1)]["hoisted"] == 1
