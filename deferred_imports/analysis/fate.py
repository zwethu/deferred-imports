"""E2 (RQ2): what happens to a deferred module pair over the project's history.

Plan:
- Start: the first commit where pair A -> B exists only through deferred imports.
- Outcomes:
  * promoted: the pair gains an eager import (any statement, not only the same one moved),
  * removed: all deferred imports of the pair are gone and there is no eager one,
  * kept: still deferred-only at the last mined commit (censored).
- Lifetime in active commits, with calendar days as a check.
- Kaplan-Meier survival curve; Aalen-Johansen for promoted vs removed (competing risks).
- A second person re-checks 30 promotions (R3).
"""
