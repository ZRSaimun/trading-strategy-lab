# Local declared-holdout population overlap lock

This opt-in, offline defense in depth is built on the local SQLite one-attempt registry in PR #151. It prevents *cooperating registrations using the same database* from reusing any declared feed row across different study IDs or candidates. It is not proof of a genuinely untouched holdout, authenticated historical data, a trusted timestamp, or a profitable strategy.

Before the declared holdout begins, construct a valid manifest and its exact chronological census, then call:

```python
from app.local_holdout_population_lock import register_population_locked_holdout

registration = register_population_locked_holdout("/private/holdout.sqlite", manifest, census)
```

This validates the manifest and full census using the declared-only gate, computes a canonical digest of the declared market feed (provider, venue, instrument, quote side and UTC convention), independent of account alias and archive digest, and inserts the study claim and every `(declared feed, row SHA-256)` pair in one `BEGIN IMMEDIATE` SQLite transaction. An identical or *partially overlapping* source population is rejected even when the study ID, candidate, or declared holdout interval changes. A duplicate study is also rejected. Failed inserts roll back all rows and the study claim. To evaluate later, use the existing `audit_declared_holdout_release_once` wrapper; a failed evaluation consumes the single local release attempt.

**Important limits:** The existing `register_local_holdout` function remains available for backward compatibility but **does not reserve population rows**. Registrations made using it, or in another database, are not covered by this overlap lock. Caller-declared feed identities and row digests can be falsified or changed; two representations of the same underlying data may bypass the lock. A local database can be restored, edited or replaced, and raw outcomes can be inspected outside this interface. This is an optional local research guard, **not** an independently trusted cross-host registry or a production security boundary. It never reads market archives, contacts a broker, places paper or real orders, or changes production routes.

Synthetic tests cover exact and partial overlap, atomic rollback, duplicate studies, disjoint populations, separate declared feeds, invalid declarations, early registration and concurrent registration. Run from `backend` with `PYTHONPATH=. python -m pytest -q tests/test_local_holdout_population_lock.py`.

**Mixed-mode fail-closed rule:** Once this database has a population-lock table, `register_local_holdout` rejects any new legacy, unreserved registration. If legacy study claims already exist before the first population lock, `register_population_locked_holdout` refuses to activate the lock in that database; it does not silently grandfather or migrate those claims. Use a separate, explicitly managed clean registry for new protected studies, while preserving old records. This prevents the same-database legacy-registration bypass among cooperating callers, but does **not** prevent another SQLite file, direct database tampering, forged row hashes, or direct raw-outcome access. No existing claims or rows are deleted or rewritten.
