from deferred_imports.analysis.cycles import reachable, sccs
from deferred_imports.analysis.graphs import is_deferred, split_pairs


def test_is_deferred():
    assert is_deferred("in_function")
    assert is_deferred("type_checking")
    assert is_deferred("in_function+try_except")
    assert not is_deferred("top_level")
    assert not is_deferred("try_except")  # top-level try/except still runs at load time


def test_split_pairs():
    w = {("a", "b"): {"top_level": 1, "in_function": 2},   # eager wins
         ("b", "a"): {"in_function": 1},                    # deferred-only
         ("c", "a"): {"try_except": 1}}                     # eager
    eager, dfo = split_pairs(w)
    assert eager == {("a", "b"), ("c", "a")}
    assert dfo == {("b", "a")}


def test_sccs_any_length():
    assert sccs([("a", "b"), ("b", "c")]) == []
    assert sccs([("a", "b"), ("b", "c"), ("c", "a")]) == [{"a", "b", "c"}]
    got = sorted(map(sorted, sccs([("a", "b"), ("b", "a"), ("c", "d"), ("d", "e"), ("e", "c"),
                                   ("b", "c")])))
    assert got == [["a", "b"], ["c", "d", "e"]]


def test_reachable():
    assert reachable([("a", "b"), ("b", "c")], "a") == {"b", "c"}
