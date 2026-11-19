# Corpus for the deferred-imports study

The full list with pinned commits is in [`corpus/paper-corpus.csv`](../corpus/paper-corpus.csv).
We mine each repository at its pinned commit, so results can be repeated.

**24 repositories, about 185,360 first-parent commits in total.**

| Group | Count | Why it is in the study |
|---|---|---|
| Well-known | 10 | Popular, heavily reviewed projects. The baseline. |
| Less-scrutinized | 10 | Long-lived projects with fewer outside reviewers, where architectural mistakes are more likely to stay. |
| AI-heavy | 4 | Many coding-agent commits. Only for variety; agents are one sentence in the paper. |

## Selection rules (all groups)

- Python is the main language.
- At least 8 years of history (except the AI-heavy group) and at least 2,000 first-parent commits.
  Long history matters for RQ2, which follows deferred imports over time.
- Still maintained: commits in the last 12 months.
- At least 10 contributors, so no personal or toy projects
  (see Kalliamvakou et al., "The promises and perils of mining GitHub", MSR 2014).
- Repositories from our earlier screened corpus (`corpus/repos.csv`) keep their pinned commit.
  New repositories are pinned at the default-branch head on 17-18 Nov 2026.

## Well-known (10)

| Repo | Kind | Years | First-parent commits | Pinned commit | Source |
|---|---|---|---|---|---|
| [django](https://github.com/django/django) | library | 21 | 34,038 | `dab0a5c47f` (2026-10-09) | corpus/repos.csv |
| [numpy](https://github.com/numpy/numpy) | library | 25 | 20,543 | `c20f5fd1be` (2026-11-17) | new 2026-11-18 |
| [saleor](https://github.com/saleor/saleor) | application | 13 | 7,030 | `782a751f62` (2026-10-09) | corpus/repos.csv |
| [netbox](https://github.com/netbox-community/netbox) | application | 10 | 2,167 | `3c6fce6520` (2026-10-10) | corpus/repos.csv |
| [celery](https://github.com/celery/celery) | library | 17 | 8,129 | `ed354d9100` (2026-10-10) | corpus/repos.csv |
| [scrapy](https://github.com/scrapy/scrapy) | library | 17 | 5,697 | `be7bdc4cd1` (2026-10-09) | corpus/repos.csv |
| [pip](https://github.com/pypa/pip) | tool | 17 | 5,360 | `a7002c9771` (2026-09-23) | corpus/repos.csv |
| [poetry](https://github.com/python-poetry/poetry) | tool | 8 | 3,313 | `63bba274f8` (2026-10-06) | corpus/repos.csv |
| [pylint](https://github.com/pylint-dev/pylint) | tool | 20 | 8,518 | `360ed2326b` (2026-10-11) | corpus/repos.csv |
| [certbot](https://github.com/certbot/certbot) | tool | 14 | 4,395 | `0201ba5ce7` (2026-10-07) | corpus/repos.csv |

## Less-scrutinized (10)

"Less-scrutinized" does not mean bad code. It means fewer people review the code, so mistakes
can stay longer than in a popular project. We use two signals that anyone can measure:

- **Fewer than 1,000 GitHub stars** (fewer outside eyes), and
- **a small core team**: one developer writes a large share of the first-parent commits.

| Repo | Kind | Years | First-parent commits | Pinned commit | Source |
|---|---|---|---|---|---|
| [relate](https://github.com/inducer/relate) | application | 12 | 2,702 | `18e51ddd37` (2026-11-17) | new 2026-11-18 |
| [opendrift](https://github.com/OpenDrift/opendrift) | library | 13 | 3,355 | `7173c92e0e` (2026-11-17) | new 2026-11-18 |
| [oq-engine](https://github.com/gem/oq-engine) | application | 16 | 14,938 | `88a8657bba` (2026-11-17) | new 2026-11-18 |
| [osf.io](https://github.com/CenterForOpenScience/osf.io) | application | 13 | 4,793 | `84dbb4344e` (2026-11-16) | new 2026-11-18 |
| [the-blue-alliance](https://github.com/the-blue-alliance/the-blue-alliance) | application | 16 | 11,236 | `750f8b0bcc` (2026-11-17) | new 2026-11-18 |
| [kpi](https://github.com/kobotoolbox/kpi) | application | 11 | 3,769 | `ab6233b5db` (2026-11-17) | new 2026-11-18 |
| [Sefaria-Project](https://github.com/Sefaria/Sefaria-Project) | application | 9 | 5,517 | `7347309c26` (2026-11-17) | new 2026-11-18 |
| [archivematica](https://github.com/artefactual/archivematica) | application | 14 | 3,663 | `d1805644d3` (2026-11-17) | new 2026-11-18 |
| [landlab](https://github.com/landlab/landlab) | library | 13 | 2,176 | `5c2049547b` (2026-11-17) | new 2026-11-18 |
| [dipy](https://github.com/dipy/dipy) | library | 17 | 3,100 | `a252adb68d` (2026-10-07) | corpus/repos.csv |

Measured on 17 Nov 2026 from a clone of the default branch (stars from the GitHub search API):

| Repo | Stars (approx.) | Authors | Top author share | First-parent merge share |
|---|---|---|---|---|
| relate | 437 | 14 | 81% | 15% |
| opendrift | 337 | 31 | 60% | 30% |
| oq-engine | 472 | 51 | 76% | 58% |
| osf.io | 733 | 56 | 54% | 74% |
| the-blue-alliance | 455 | 119 | 38% | 4% |
| kpi | 191 | 48 | 14% | 55% |
| Sefaria-Project | 774 | 60 | 29% | 35% |
| archivematica | 527 | 84 | 16% | 2% |
| landlab | 452 | 48 | 24% | 35% |

Merge share is not used as a selection rule: a low value can mean squash or rebase merging,
not missing review.

## AI-heavy (4)

The four agent-heavy repositories from our earlier corpus with the longest history.

| Repo | Kind | Years | First-parent commits | Pinned commit | Source |
|---|---|---|---|---|---|
| [lutris](https://github.com/lutris/lutris) | application | 16 | 8,748 | `3307967c2f` (2026-10-17) | corpus/repos.csv |
| [awx](https://github.com/ansible/awx) | application | 13 | 12,157 | `6fc51b6d25` (2026-10-15) | corpus/repos.csv |
| [haystack](https://github.com/deepset-ai/haystack) | library | 6 | 6,434 | `38cc7a6789` (2026-10-19) | corpus/repos.csv |
| [kornia](https://github.com/kornia/kornia) | library | 8 | 3,582 | `2343c4212b` (2026-10-19) | corpus/repos.csv |

## Python 2 history

Several repositories have Python 2 code in their early history. Python 3's `ast` cannot parse it,
so `verify.py` skips those files. Before the cut-off date in `corpus/resolver.csv` (`py2_until`),
the resolver also allows Python 2 implicit relative imports (`import models` inside a package).

The date is the first commit on the first-parent line after which the code has no Python 2
implicit relative imports left, usually the Python 3 port commit. Before it, an import may also
resolve to a file in the same folder. Checked on 19 Nov 2026:

| Repo | `py2_until` | Evidence |
|---|---|---|
| numpy | 2013-04-02 | `a939f2aa83` PR #3178: the 2to3 import fixer turns implicit relative imports into explicit ones (370 in one commit) |
| oq-engine | 2012-06-08 | `a0501ae685`: last implicit relative imports removed (haz-src-db-import refactor); later Python 2 code uses absolute imports |
| osf.io | 2019-10-15 | `63e282efb0` "[Py3][ENG-491] Ultimate backwards compatible Python 3 (#9047)" |
| the-blue-alliance | 2020-05-27 | `4b2adef79` "Starting fresh py3 migration. Move old files to old_py2." |
| Sefaria-Project | 2019-11-12 | `4fba57b396` 2to3 run on sefaria, reader, scripts (224 relative imports added) |
| kpi | 2020-04-30 | `0775d3d209` merge of PR #2315, which brings the Python 3 upgrade (#2460, #2504) to the main line |
| django, saleor | 2017-01-18, 2017-12-14 | already in `resolver.csv` |

relate needs no date. In snapshots from 2015, 2016, 2018 and 2019 the only same-folder-looking
imports are `celery` in `relate/celery.py` (the celery library) and `code_feedback` in
`course/page/code_runpy_backend.py` (on the path of the separate code-runner image).

Later dates when Python 2 left CI (for example numpy 2018-12-08, oq-engine 2018-07-03) are not used:
by then the code already ran on both versions, so implicit relative imports were gone.

**Known limit: the-blue-alliance.** After 2020-05-27 an `old_py2/` folder with Python 2 code stays
in the tree (209 files at the pinned commit). Its imports are resolved with Python 3 rules. Setting
the cut-off changed 82 edge rows in this repository and none of its episode counts.

## Threats to note in the paper

- The groups use simple signals (stars, core-team share). They are proxies for review effort, not a direct measure.
- In less-scrutinized projects, results can reflect one developer's habits, so we report per-repository numbers (plan R2).
- AI-heavy projects are young, so they add little to RQ2.
