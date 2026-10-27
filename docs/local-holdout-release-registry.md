# Local holdout release attempt fence (offline defense in depth)

`backend/app/local_holdout_release_registry.py` is an optional SQLite one-attempt fence for the **declared-only** holdout gate in PR #151. It is not a trusted timestamp service or independently immutable preregistration registry. No network, brokerage API, paper/live orders, archive reads or production routes are involved.

1. Before the holdout starts, freeze a manifest and calculate its digest with `prepare_declared_holdout_manifest_sha256(manifest)`. Call `register_local_holdout(path, study_id=manifest["study_id"], manifest_sha256=digest, holdout_start_at_utc=..., holdout_end_at_utc=...)` using the exact manifest clocks. The host clock must precede the declared start. Re-registration of the same study ID fails, even if the digest matches.
2. After the holdout ends, call `audit_declared_holdout_release_once(path, manifest, census, anchor, lambda: load_outcomes())` **instead of** the unguarded declared audit if local one-attempt protection is desired. The wrapper first atomically consumes the release claim in a SQLite `BEGIN IMMEDIATE` transaction and only then calls the supplied outcome loader and evaluates outcomes using the host wall-clock release time. A crash or invalid outcome **burns** the claim; it does not retry, because a retry could become an outcome-peeking channel.
3. The claim result explicitly reports `independently_trusted_registry: false`. The underlying audit continues to report that independent holdout untouchedness, archive authenticity and profitability are unverified.

The registry uses a primary key on study ID, a persisted manifest digest and declared holdout end, an atomic `release_claimed_at_utc` update, and SQLite FULL synchronous writes. Tests include 24 concurrent claim attempts with exactly one successful claim, early release, clock rollback, malformed identity, duplicate registration and persistence across connections.

**Limitations:** A local DB file can be copied, restored, deleted or edited by an operator; the host wall clock can be changed; the caller controls the initial manifest and source digests; and the raw outcome data may remain accessible outside this API. A caller may load or inspect outcomes before providing the loader; this wrapper only defers access for cooperating callers. SQLite transactions only serialize cooperating callers on the same database. The registry is **not** externally timestamped, immutable, tamper-proof, cross-host, or proof of a single real-world evaluation. Do not deploy this as a trusted holdout service without a separately controlled immutable registry, authenticated source bytes, access controls, backup/rollback policy and independent review. The one-attempt fence is a fail-closed research safety feature, not an order authorization.

Run isolated tests from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_local_holdout_release_registry.py
```

All test timestamps and digests are invented; no trading returns, executable spreads or actual financing rates were measured.
