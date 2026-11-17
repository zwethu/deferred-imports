"""E3 (RQ1, cycles): cycles that appear only when deferred edges are included.

Plan:
- Find strongly connected components (SCCs) in the top-level graph and in the full graph.
  An SCC is a group of modules that can all reach each other, so cycles of any length count.
- Hidden cycle = an SCC (or a larger SCC) that exists only in the full graph.
- Report per repo: number and size of SCCs in both graphs, largest SCC, and the share of
  deferred-only pairs that close a cycle (B can reach A in the full graph).
- Two people hand-check about 30 cycle-closing deferred edges (R3).
"""
