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
reservation tables exist, the exact row set, decision-time set, and
row-to-decision pairing set must all match. This
detects balanced row replacement, shifted decision timestamps and even a
consistent replacement of the source key in both reservation tables that
the earlier count and one-source checks could miss. A mismatch rejects the
claim **before outcome loading** and leaves the attempt unconsumed. The
claim response's `local_frozen_population_matched` is `true` only when
the exact locked sets were compared; direct legacy calls without frozen
population arguments and unreserved legacy registries report `false`.
A frozen-census release now **requires all three reservation tables**: an old
legacy registry with no population lock is rejected before outcome loading,
leaving the attempt unconsumed. Direct legacy claims *without* a frozen
census remain available for compatibility, but report
`local_frozen_population_matched: false` and provide no population proof.
Existing legacy studies must not be silently upgraded or backfilled from
post-holdout observations; use a newly preregistered population-locked study.
This does not establish external archive authenticity or prevent rewriting
the caller's manifest and database together. The paired reservation table additionally detects a balanced swap of
row-to-decision associations, but does **not** independently attest the
original market-source pairing or prevent rewriting the database and manifest
together. Existing pairless registries cannot be backfilled safely. Do not interpret this local comparison as independent
holdout verification or permission to place orders.


**Transactional clock recheck (27 October 2026):** Both local registration and one-attempt release now sample the local UTC clock again inside the SQLite writer transaction. A registration that crosses the holdout start while waiting for the lock or performing writes rolls back, and the persisted registration time is the final precommit clock sample. A release claim rejects a clock rollback before consuming the attempt and persists the final sample. Synthetic tests simulate both timing races. This only protects against local timing inconsistencies: host clocks remain untrusted, and an attacker can still alter or restore SQLite or access outcomes outside the wrapper.


**Pre-claim frozen-census validation (27 October 2026):** The guarded
`audit_declared_holdout_release_once` wrapper now validates the complete
declared census against its manifest commitment **before** consuming a local
one-attempt release claim or invoking the outcome loader. Previously a
legacy/unreserved registry could allow a malformed, reordered or altered
census to reach the outcome loader before the later declared audit rejected
it. Four synthetic regression cases cover reordered, altered, missing and
cross-source census rows; each verifies no outcome-loader call and no
consumed release attempt. A *valid* evaluation still consumes the one
attempt before loading outcomes, even if outcome evaluation subsequently
fails. This is caller-side consistency checking, **not** authenticated
market history, independent preregistration, or prevention of raw data
access outside the cooperating wrapper.


**Declared anchor preflight (27 October 2026):** The guarded wrapper now
validates the exact anchor declaration schema, frozen manifest digest,
registration-to-holdout anchor chronology, reference identity, and receipt
digest **before** consuming the local one-attempt release claim or invoking
the outcome loader. The standalone declared audit reuses the same validator.
Six synthetic invalid-anchor variants verify that no outcomes are loaded,
the claim remains unconsumed, and a later valid declared anchor can still
release once. This closes a premature outcome-loader exposure path for
malformed anchor declarations, but **does not authenticate** the anchor,
prove that an external record exists, or stop raw outcome access outside
the cooperating wrapper. Never interpret the declared anchor as independent
preregistration evidence.


**Direct-claim verification fence (27 October 2026):** A direct
`claim_local_holdout_release` call against a population-locked registry
now **requires** the exact frozen `expected_population_rows` (row hash and
decision timestamp pairs) and `expected_source_key_sha256`. Omitting
either cannot consume the release claim. This closes the accidental
unverified-claim path that previously burned a population-locked study
while returning `local_frozen_population_matched: false`. The synthetic
regression checks rejection, durable non-consumption, a successful
exact-pair claim and the subsequent one-attempt rejection. An unreserved
legacy registry still permits a direct claim without census verification,
but reports `local_frozen_population_matched: false`. This is a
compatibility-breaking safety requirement **only** for direct callers
against population-locked registries; update those callers to supply the
frozen census or use the guarded wrapper. It does not establish
independent source authentication, immutable external preregistration or
profitable backtest results.


**Persisted-clock chronology guard (27 October 2026):** Before consuming
any direct or guarded local release, the SQLite transaction now checks
that the persisted registration, start and end timestamps are exact
nonnegative integers satisfying `registered < start < end` and the
bounded timestamp range. SQLite INTEGER affinity alone can store a
fractional number, and its existing CHECK permits negative registration
timestamps. Four synthetic corruption cases verify that such records
cannot consume the sole release attempt, while a corrected record
can still be claimed once. This detects inconsistent local records
only; it does not independently timestamp registration or protect
against coordinated database restoration/tampering.

**Partial population-schema legacy fence (28 October 2026):** A new
`register_local_holdout` call now rejects a SQLite database containing
**any** of the three population-reservation tables, not only the row table.
A decisions-only, pairs-only, or other incomplete reservation schema must
not silently admit an unreserved legacy study and obstruct later
source-identity-aware registration. Five synthetic schema-presence
regressions verify rejection and transaction rollback without creating a
claim. This is a local integrity guard, not proof that an external source
or preregistration is authentic. Existing unreserved legacy databases
without any reservation tables retain their compatibility path.
