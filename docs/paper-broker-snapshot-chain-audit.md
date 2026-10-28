# Disconnected broker snapshot chain audit (Loop 4)

`backend/app/paper_broker_snapshot_chain_audit.py` checks **2–16** caller-declared
broker inventory snapshots and their corresponding caller-supplied check times.
It reuses the bounded inventory census and adjacent snapshot replay fence, then
rejects snapshot-ID reuse anywhere in the chain, including nonadjacent reuse
(e.g. `snapshot1 → snapshot2 → snapshot1`) that pairwise comparison misses.
It also propagates gaps, regressions, changed fill receipts, account identity
changes and other pairwise HOLD reasons. **Individually fresh snapshots can
still conceal a long unobserved interval:** consecutive trusted-caller check
times and consecutive observation timestamps must each be no more than
60,000 ms apart by default. The optional `max_checkpoint_gap_ms` policy can
only tighten that ceiling (strict positive integer, maximum 60,000 ms).
Violations are `trusted_checkpoint_gap` and `snapshot_observation_gap`
HOLD reasons; the exact boundary is permitted. Legitimate slow polling or
outages may produce HOLDs requiring separate investigation. Intermediate `OPEN`/`PARTIAL` inventories
may have only the `unresolved_order_state` census warning; the final census must
be terminal and clean. Invalid schemas or overlong chains raise `ValueError`.

`DECLARED_CHAIN_CANDIDATE_UNVERIFIED` means only that these *declared* records
are internally consistent under these bounded checks. Snapshot IDs, clock
readings, receipts, pagination and account identity are **not broker-authenticated**.
The caller could omit earlier snapshots, replace the entire history, or supply
fabricated evidence. No persistent history or external audit anchor is created.
False-positive HOLDs can occur with legitimate delayed broker corrections.

All authentication, UNKNOWN-release and paper/live order flags are always
`false`. The module performs no network calls, file/database writes, broker
order placement, credential access or deployment. It cannot authorize a retry
of a non-idempotent order. Next integration must use independently authenticated
provider receipts, complete cursor/snapshot semantics, durable trusted replay
checkpoints, the UNKNOWN submission ledger, atomic risk reservations, protective
stops and separate positive human approval for each real-money order. No
brokerage API eligibility or profitable outcome is inferred.
