# deferred-imports

Code and data for our study of **deferred imports** in Python (JCSSE 2027).

## What we study

A deferred import is an import that does **not** run when its module is loaded:

```python
def refund():
    from orders import Order      # in-function: runs only when refund() is called

if TYPE_CHECKING:
    from orders import Order      # type-only: never runs, only type checkers read it
```

A top-level `try: import x / except ImportError:` still runs at load time, so it is
**not** deferred. We keep it apart.

The code still depends on the imported module, but a checker that reads only
top-level imports does not see it. Deferred imports can hide import cycles.

## Research questions

- **RQ1** (E1, E3): How much of a project's module dependency structure exists only
  through deferred imports, and which cycles appear only when we add them?
- **RQ2** (E2): What happens to a deferred module pair over time: promoted to an
  eager import, removed, or kept, and for how long?

## Layout

```
deferred_imports/
  mining/      miner (from SENSO-Lens): git history -> SQLite event log, import kinds
  analysis/    graphs.py (E1), cycles.py (E3), fate.py (E2)  -- not written yet
corpus/        repos.csv (pinned repositories), resolver.csv (source roots, py2 cut-offs)
tests/
```

## Setup

```bash
uv sync
uv run pytest
```

## Mine one repository

```bash
uv run python -m deferred_imports.mining.mine ../corpus-clones/poetry --rev <pinned_sha>
uv run python -m deferred_imports.mining.edges index/poetry.sqlite
uv run python -m deferred_imports.mining.check ../corpus-clones/poetry index/poetry.sqlite
```

Use the `pinned_sha` from `corpus/repos.csv`. Output goes to `index/` (ignored by git).

Each import is tagged by where it sits: `top_level`, `in_function`, `type_checking`,
`try_except` (or a mix, like `in_function+try_except`).

## Known TODO

- Miner fix (found 15 Nov): imports under `if False:` are tagged eager, and imports under
  `if not TYPE_CHECKING:` are tagged type-only. Fix before mining new repositories.

## Origin

The miner is copied from the SENSO-Lens project (`senso_lens/mining`, branch `main`),
without the churn, rule-induction and server code.

## License

MIT, see [LICENSE](LICENSE). To cite, see [CITATION.cff](CITATION.cff).
