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
- At least 9 years of history (except the AI-heavy group) and at least 2,000 first-parent commits.
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

## Python 2 history (TODO before analysis)

Several repositories have Python 2 code in their early history. Python 3's `ast` cannot parse it,
so `verify.py` skips those files, and the analysis should start after the move to Python 3.
`corpus/resolver.csv` holds the cut-off date per repository (`py2_until`).

Candidate dates found in commit messages (17 Nov 2026), **not checked yet**:

| Repo | Candidate | Evidence |
|---|---|---|
| osf.io | 2020-01-15 | `e77ca44d89` "[ENG-492] Py3 Conversion (#9054)" |
| the-blue-alliance | 2020-05 to 2021-11 | py3 rewrite started in `4b2adef79` (2020-05-27, old code moved to `old_py2/`); `309850ccb` (2021-11-20) drops py2 from the dev setup. Exclude `old_py2/`. |
| Sefaria-Project | ~2019-12 | `8ad8b8d76` "convert to python 3" (2019-12-04) |
| kpi | ~2019-08 | `python3-upgrade` branch merged around 2019-08-22 |
| relate | ~2016-08 | Py3 database migration commits (2016-08-08); supported both for a while |
| numpy | ~2019 | Python 2 dropped for NumPy 1.17; exact commit to find |
| oq-engine | to find | |
| django, saleor, celery, ... | already in `resolver.csv` or no Python 2 era | check |

## Threats to note in the paper

- The groups use simple signals (stars, core-team share). They are proxies for review effort, not a direct measure.
- In less-scrutinized projects, results can reflect one developer's habits, so we report per-repository numbers (plan R2).
- AI-heavy projects are young, so they add little to RQ2.
