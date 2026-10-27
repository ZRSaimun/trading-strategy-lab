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


**Frozen interval binding (27 October 2026):** The guarded
`audit_declared_holdout_release_once` wrapper now passes both holdout
interval endpoints from the frozen manifest into the atomic SQLite claim.
If either stored endpoint differs, the claim is rejected **before** loading
outcomes and remains unconsumed. A direct legacy call to
`claim_local_holdout_release` may omit these optional endpoints for
backward compatibility, so direct callers do **not** gain this check
automatically. Tests cover edited start/end values, malformed or partial
expected intervals, and preservation of the unconsumed claim. This detects
inconsistent local records, not deliberate rewriting of both manifest and
database or independently authenticated preregistration.


**Frozen population binding (27 October 2026):** For a nonempty declared census,
the guarded `audit_declared_holdout_release_once` wrapper now passes its
frozen row SHA-256 values, decision timestamps, and declared market-feed key
into the *same SQLite transaction* that claims the release. When population
reservation tables exist, both exact reservation sets must match. This
detects balanced row replacement, shifted decision timestamps and even a
consistent replacement of the source key in both reservation tables that
the earlier count and one-source checks could miss. A mismatch rejects the
claim **before outcome loading** and leaves the attempt unconsumed. The
claim response's `local_frozen_population_matched` is `true` only when
the exact locked sets were compared; direct legacy calls without frozen
population arguments and unreserved legacy registries report `false`.
This does not establish external archive authenticity or prevent rewriting
the caller's manifest and database together. The schema stores row hashes
and decision times in separate sets, so it does **not** attest their original
one-to-one pairing. Do not interpret this local comparison as independent
holdout verification or permission to place orders.
