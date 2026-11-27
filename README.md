# deferred-imports

Code, data, hand-check results and validator for our study of **deferred imports** in
Python (JCSSE 2027).

## What is in this repository

| You want | Where to look |
|---|---|
| **Code** that mines the repositories and computes every number and figure | [`deferred_imports/`](deferred_imports), [`scripts/`](scripts) — see [Code](#code) |
| **Data**: the 24 repositories and pinned commits, the result tables, the mined databases | [`corpus/`](corpus), [`data/`](data), Zenodo — see [Data](#data) |
| **Hand check**: the sampled cases and the five checkers' answers | [`handcheck/`](handcheck), [`results/`](results) — see [Hand check](#hand-check) |
| **Validator**: an independent re-check of the mined data against git | [`deferred_imports/mining/verify.py`](deferred_imports/mining/verify.py), [`scripts/verify_all.sh`](scripts/verify_all.sh) — see [Validator](#validator) |

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

### Research questions

- **RQ1 (Prevalence):** What share of each project's file-to-file dependencies exists
  only through deferred imports?
- **RQ2 (Cycles):** Which projects show cycles only in the full import graph? How
  does the largest strongly connected component change when deferred imports are added?
- **RQ3 (Evolution):** How long does a dependency stay deferred-only after it first
  enters that state? What shares gain an eager import, disappear, or remain deferred-only
  at the pinned commit?

RQ1 and RQ2 use the pinned commit. RQ3 follows dependencies through the project history.

## Code

```
deferred_imports/
  mining/      git history -> one SQLite event log per repository (mine.py, edges.py),
               self-check (check.py) and the independent validator (verify.py)
  analysis/    graphs.py (RQ1), cycles.py (RQ2), fate.py (RQ3), bootstrap.py (confidence
               intervals), promotion_kinds.py, handcheck.py (hand-check samples)
  figures/     one module per figure and Table I
scripts/
  clone_corpus.sh    clone the 24 repositories into ../clones
  run_experiment.sh  the whole pipeline: clone, mine, analyze, generate hand-check samples
  make_figures.sh    every figure and table in the paper, into out/figures/
  verify_all.sh      run the validator on every mined repository
tests/
```

Setup and tests:

```bash
uv sync
uv run pytest
```

Run everything (clones go to `../clones`, mined databases to `index/`, results to `out/`):

```bash
bash scripts/run_experiment.sh
bash scripts/make_figures.sh
```

Print Table II (RQ3 outcomes) from the shared data, without mining anything:

```bash
uv run python -m deferred_imports.figures.table2_fates data/e2_episodes.csv
```

Or mine one repository by hand, at the `pinned_sha` from `corpus/paper-corpus.csv`:

```bash
uv run python -m deferred_imports.mining.mine ../clones/poetry --rev <pinned_sha>
uv run python -m deferred_imports.mining.edges index/poetry.sqlite
uv run python -m deferred_imports.mining.check ../clones/poetry index/poetry.sqlite
```

Each import is tagged by where it sits: `top_level`, `in_function`, `type_checking`,
`try_except` (or a mix, like `in_function+try_except`). Imports in a branch that never
runs are tagged `type_checking` too: the body of `if TYPE_CHECKING:` / `if False:`, and
the `elif`/`else` parts of `if not TYPE_CHECKING:`. This rule came in miner 0.4.0;
databases from 0.3.0 must be mined again.

## Data

| File | What it holds |
|---|---|
| [`corpus/paper-corpus.csv`](corpus/paper-corpus.csv) | The 24 repositories: group, URL, kind, **pinned commit** and date, size, history |
| [`corpus/resolver.csv`](corpus/resolver.csv) | Per repository: extra source roots for import resolution, and the Python 2 cut-off date |
| [`corpus/repos.csv`](corpus/repos.csv) | The older, larger screened list the corpus was chosen from |
| [`docs/corpus.md`](docs/corpus.md) | How and why each repository was chosen |

The results behind the paper's numbers and figures are in [`data/`](data), at the file level for all 24 repositories:

| File | What it holds |
|---|---|
| [`data/e1_share.csv`](data/e1_share.csv) | RQ1: per repository, eager and deferred imports and the share of file pairs linked only by deferred imports |
| [`data/e3_cycles.csv`](data/e3_cycles.csv) | RQ2: per repository, import cycles with and without deferred imports, and the deferred-only pairs that participate in a cycle |
| [`data/e2_fate.csv`](data/e2_fate.csv) | RQ3: per repository, how many deferred pairs were gained an eager import, disappeared, or remained deferred-only |
| [`data/e2_episodes.csv`](data/e2_episodes.csv) | RQ3: one row per deferred episode of a file pair, with its start, end, outcome and length |
| [`data/verify_summary.csv`](data/verify_summary.csv) | Validator: per repository, values checked, mismatches and PASS/FAIL |

`scripts/make_figures.sh` writes the same files (as `out/figures/share.csv`, `cycles.csv`,
`fate.csv`, `episodes.csv`) from the mined databases.

**Mined databases.** The 24 SQLite event logs (`index/<repo>.sqlite`, about 290 MB) are on
Zenodo as `deferred-imports-index.tar.gz` (82 MB):
[doi:10.5281/zenodo.24538361](https://doi.org/10.5281/zenodo.24538361).
SHA-256: `9fc98fcbb83d661b3a611c6c4f1e54a225c33e9b9a3de3e464eb20f2fb76829c`.
Unpack it in the repository root to get `index/`. Authors are stored only as a salted hash,
and commit messages are not stored. The tables are described in
[`deferred_imports/mining/schema.sql`](deferred_imports/mining/schema.sql).

Every result is computed from the history up to the pinned commit, so you can also
rebuild the databases yourself: `scripts/run_experiment.sh` clones the repositories and
mines them at their pinned commits.

## Hand check

To check that the miner finds real deferred imports, people checked a random sample of
cases by hand on GitHub.

| File | What it holds |
|---|---|
| [`handcheck/file-level-2026-11-19/promotions.csv`](handcheck/file-level-2026-11-19/promotions.csv) | 60 sampled promotions (RQ3), one row per import line (154 rows) |
| [`handcheck/file-level-2026-11-19/cycle_edges.csv`](handcheck/file-level-2026-11-19/cycle_edges.csv) | 60 sampled deferred imports that close a cycle (RQ2), one row per import line (553 rows) |
| [`results/promotions_checker1.csv`](results) … `checker5.csv` | Each checker's answers for the promotions sample |
| [`results/cycle_edges_checker1.csv`](results) … `checker5.csv` | Each checker's answers for the cycle sample |

Each row has the file, line, commit, a GitHub link that opens that exact line, and the
import kind the miner gave it (`kind`). The checker fills in `ok (yes/no)` and, where
needed, a `note`. What counts as
`yes` is written at the top of
[`deferred_imports/analysis/handcheck.py`](deferred_imports/analysis/handcheck.py).
The samples are drawn with a fixed seed, so this command makes the same rows again:

```bash
uv run python -m deferred_imports.analysis.handcheck index/*.sqlite --out handcheck --n 60
```

## Validator

[`deferred_imports/mining/verify.py`](deferred_imports/mining/verify.py) checks a mined
database against git **without using any other code from this repository**. It
recomputes everything from plain git commands and Python's `ast` (the miner uses
tree-sitter), rebuilds the import graph from the whole tree at checkpoints, and compares
every value with the database. The checks are listed at the top of the file.

```bash
uv run python -m deferred_imports.mining.verify ../clones/poetry index/poetry.sqlite --out poetry.json
bash scripts/verify_all.sh            # every repository; summary in out/verify/summary.csv
```

On our run all 24 repositories pass with no mismatches.

## License

MIT, see [LICENSE](LICENSE). To cite, see [CITATION.cff](CITATION.cff).
