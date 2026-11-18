"""E3 (RQ1, cycles): cycles that appear only when deferred edges are included.

A strongly connected component (SCC) is a group of nodes that can all reach each other,
so cycles of any length count (A->B->A, A->B->C->A, ...).

For each repository we compare the eager graph with the full graph (eager + deferred):
  - number of nodes that sit in a cycle, number of SCCs, size of the largest SCC,
  - deferred-only pairs that close a cycle: A -> B is deferred-only and B can reach A.

Run:
    uv run python -m deferred_imports.analysis.cycles index/*.sqlite [--level file] [--csv out.csv]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from deferred_imports.analysis.graphs import pair_weights, split_pairs


def sccs(edges) -> list[set]:
    """Strongly connected components with 2+ nodes (iterative Tarjan)."""
    adj = defaultdict(list)
    nodes = set()
    for a, b in edges:
        adj[a].append(b)
        nodes |= {a, b}
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = counter[0]; counter[0] += 1
        stack.append(root); on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]; counter[0] += 1
                    stack.append(w); on.add(w)
                    work.append((w, iter(adj[w])))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = set()
                    while True:
                        w = stack.pop(); on.discard(w); comp.add(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        out.append(comp)
    return out


def reachable(edges, start) -> set:
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    seen, todo = set(), [start]
    while todo:
        for n in adj[todo.pop()]:
            if n not in seen:
                seen.add(n); todo.append(n)
    return seen


def closing_pairs(full_sccs: list[set], dfo) -> list[tuple]:
    """Deferred-only pairs A -> B that close a cycle: A and B sit in the same SCC of the full
    graph, so B can reach A again."""
    comp_of = {n: k for k, c in enumerate(full_sccs) for n in c}
    return sorted(((a, b) for a, b in dfo if a in comp_of and comp_of.get(a) == comp_of.get(b)),
                  key=str)


def shortest_path(edges, start, goal) -> list | None:
    """Shortest list of nodes start, ..., goal following `edges` (breadth-first), or None."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    prev, todo = {start: None}, [start]
    for node in todo:
        if node == goal:
            path = []
            while node is not None:
                path.append(node)
                node = prev[node]
            return path[::-1]
        for n in sorted(adj[node], key=str):
            if n not in prev:
                prev[n] = node
                todo.append(n)
    return None


def summary(db: Path, level: str) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    eager, dfo = split_pairs(pair_weights(con, level))
    full = eager | dfo
    c_e, c_f = sccs(eager), sccs(full)
    closing = len(closing_pairs(c_f, dfo))
    return {
        "repo": db.stem, "level": level,
        "sccs_eager": len(c_e), "sccs_full": len(c_f),
        "nodes_in_cycles_eager": sum(map(len, c_e)), "nodes_in_cycles_full": sum(map(len, c_f)),
        "largest_scc_eager": max(map(len, c_e), default=0),
        "largest_scc_full": max(map(len, c_f), default=0),
        "deferred_only_pairs": len(dfo), "deferred_only_closing_cycle": closing,
        "share_closing": round(closing / len(dfo), 4) if dfo else None,
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--level", choices=["package", "file"], default="package")
    ap.add_argument("--csv", type=Path)
    a = ap.parse_args(argv)
    rows = [summary(db, a.level) for db in a.dbs]
    write_csv(rows, a.csv)


def write_csv(rows: list[dict], path: Path | None) -> None:
    if path is None:
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
