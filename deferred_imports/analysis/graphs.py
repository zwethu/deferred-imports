"""E1 (RQ1): how much of the module graph exists only through deferred imports.

Plan:
- Build two module graphs from one event log, at HEAD and at checkpoints over time:
  * top-level graph: only eager (top-level) imports,
  * full graph: eager + deferred imports.
- Deferred = in-function or type-only (inside `if TYPE_CHECKING:`).
  A top-level try/except import is still eager; keep it apart, do not count it as deferred.
- A deferred-only module pair = A -> B exists only through deferred imports.
- Report per repo: share of imports by kind, share of deferred-only pairs,
  plus per-repo median, range and a bootstrap 95% interval that resamples repositories (R2).
"""
