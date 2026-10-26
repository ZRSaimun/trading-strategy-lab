"""Offline paper-order attempt velocity review. NEVER an execution permission.

All account, policy, history, and circuit-breaker inputs are UNAUTHENTICATED
caller declarations. A passing result does not prove complete broker history.
No network calls, credentials, order sender, persistent writes or approval.
"""

from hashlib import sha256
import json
import re

MAX_MS = 8_640_000_000_000_000
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
MAX_EVENTS = 5000
MAX_SEQUENCE = 2**53 - 1
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
CANDIDATE = {"account_id", "client_order_id", "instrument", "intent_sha256", "side"}
HISTORY = {"account_id", "coverage_started_at_ms", "snapshot_at_ms", "first_sequence", "events"}
EVENT = {"client_order_id", "instrument", "intent_sha256", "side", "state", "sequence", "attempted_at_ms"}
POLICY = {"max_attempts_per_hour", "max_symbol_attempts_per_hour", "max_attempts_utc_day",
          "same_symbol_cooldown_ms", "max_symbol_side_flips_per_hour",
          "max_history_snapshot_age_ms", "emergency_latched", "daily_loss_latched"}
STATES = {"REJECTED", "PENDING", "OPEN", "CANCEL_REQUESTED", "OUTCOME_UNKNOWN", "CLOSED"}
UNCERTAIN = {"PENDING", "CANCEL_REQUESTED", "OUTCOME_UNKNOWN"}


def _fields(obj, expected, label):
    if type(obj) is not dict or set(obj) != expected:
        raise ValueError(f"Invalid {label} schema")


def _int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid {name}")
    return value


def _id(value, pattern, name):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _side(value):
    if value not in ("BUY", "SELL") or type(value) is not str:
        raise ValueError("Invalid side")
    return value


def _identity(row):
    _id(row["client_order_id"], ID, "order ID")
    _id(row["instrument"], SYMBOL, "instrument")
    _id(row["intent_sha256"], SHA, "intent digest")
    _side(row["side"])


def review_paper_order_velocity(candidate: dict, history: dict, policy: dict, *, now_ms: int) -> dict:
    """Evaluate declared attempts, including rejected/uncertain ones, without submitting.

    The snapshot must cover the previous 24 hours and be recent. Sequence gaps,
    duplicate IDs, missing coverage and ambiguous outcomes require a hold.
    A supplied complete-looking history is NOT authenticated or durable proof.
    """
    _fields(candidate, CANDIDATE, "candidate")
    _fields(history, HISTORY, "history")
    _fields(policy, POLICY, "policy")
    _int(now_ms, "server time", DAY_MS, MAX_MS)
    _id(candidate["account_id"], ID, "candidate account")
    _id(history["account_id"], ID, "history account")
    _identity(candidate)
    start = _int(history["coverage_started_at_ms"], "coverage start", 0, MAX_MS)
    snap = _int(history["snapshot_at_ms"], "snapshot time", 0, MAX_MS)
    first = _int(history["first_sequence"], "first sequence", 1, MAX_SEQUENCE)
    if type(history["events"]) is not list or len(history["events"]) > MAX_EVENTS:
        raise ValueError("History must be a bounded list")
    for key in ("emergency_latched", "daily_loss_latched"):
        if type(policy[key]) is not bool:
            raise ValueError(f"Invalid {key}")
    hourly = _int(policy["max_attempts_per_hour"], "hour cap", 1, MAX_EVENTS)
    symbol_hourly = _int(policy["max_symbol_attempts_per_hour"], "symbol hour cap", 1, MAX_EVENTS)
    daily = _int(policy["max_attempts_utc_day"], "day cap", 1, MAX_EVENTS)
    cooldown = _int(policy["same_symbol_cooldown_ms"], "cooldown", 0, HOUR_MS)
    max_flips = _int(policy["max_symbol_side_flips_per_hour"], "side flip cap", 0, MAX_EVENTS)
    max_age = _int(policy["max_history_snapshot_age_ms"], "snapshot age", 100, 60000)

    seen = set()
    sequence_ok = True
    chronology_ok = True
    prev_seq = first - 1
    prev_time = start
    hour_start = now_ms - HOUR_MS
    day_start = now_ms - (now_ms % DAY_MS)
    hour_events = []
    symbol_events = []
    day_count = 0
    duplicate_fingerprint = False
    unresolved = False
    last_symbol_at = None
    for row in history["events"]:
        _fields(row, EVENT, "attempt event")
        _identity(row)
        sequence = _int(row["sequence"], "event sequence", 1, MAX_SEQUENCE)
        attempted = _int(row["attempted_at_ms"], "event time", 0, MAX_MS)
        if type(row["state"]) is not str or row["state"] not in STATES:
            raise ValueError("Invalid attempt state")
        sequence_ok &= sequence == prev_seq + 1
        chronology_ok &= start <= attempted <= snap and attempted >= prev_time
        prev_seq, prev_time = sequence, attempted
        if row["client_order_id"] in seen:
            sequence_ok = False
        seen.add(row["client_order_id"])
        unresolved |= row["state"] in UNCERTAIN
        if attempted >= now_ms - DAY_MS and row["intent_sha256"] == candidate["intent_sha256"]:
            duplicate_fingerprint = True
        if hour_start <= attempted <= now_ms:
            hour_events.append(row)
            if row["instrument"] == candidate["instrument"]:
                symbol_events.append(row)
        if day_start <= attempted <= now_ms:
            day_count += 1
        if row["instrument"] == candidate["instrument"] and attempted <= now_ms:
            last_symbol_at = attempted if last_symbol_at is None else max(last_symbol_at, attempted)

    side_sequence = [e["side"] for e in symbol_events] + [candidate["side"]]
    flips = sum(a != b for a, b in zip(side_sequence, side_sequence[1:]))
    checks = {
        "account_matches": candidate["account_id"] == history["account_id"],
        "complete_24h_coverage_declared": start <= now_ms - DAY_MS,
        "snapshot_current": start <= snap <= now_ms and now_ms - snap <= max_age,
        "contiguous_event_sequences": sequence_ok,
        "chronological_events": chronology_ok,
        "candidate_id_not_reused": candidate["client_order_id"] not in seen,
        "candidate_intent_not_repeated_24h": not duplicate_fingerprint,
        "no_unresolved_outcomes_in_declared_history": not unresolved,
        "hourly_attempt_cap": len(hour_events) < hourly,
        "symbol_hourly_attempt_cap": len(symbol_events) < symbol_hourly,
        "utc_daily_attempt_cap": day_count < daily,
        "same_symbol_cooldown_elapsed": last_symbol_at is None or now_ms - last_symbol_at >= cooldown,
        "side_flip_churn_within_cap": flips <= max_flips,
        "emergency_latch_clear": not policy["emergency_latched"],
        "daily_loss_latch_clear": not policy["daily_loss_latched"],
    }
    canonical = {"schema": "paper-order-velocity-v1", "candidate": candidate,
                 "history": history, "policy": policy, "now_ms": now_ms}
    fingerprint = sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    return {
        "status": "ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED" if all(checks.values()) else "HOLD_RECONCILIATION",
        "checks": checks,
        "failed_checks": [name for name, ok in checks.items() if not ok],
        "attempts_last_hour": len(hour_events),
        "symbol_attempts_last_hour": len(symbol_events),
        "attempts_utc_day": day_count,
        "symbol_side_flips_last_hour_with_candidate": flips,
        "review_sha256": fingerprint,
        "history_authenticated": False,
        "broker_account_authenticated": False,
        "risk_reservation_committed": False,
        "human_approval_recorded": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warnings": [
            "Caller-declared event history, completeness and circuit breakers are NOT authenticated.",
            "A SHA-256 digest is NOT a signature, durable rate limiter or order authorization.",
            "A broker-facing gate requires transactionally persisted attempts, authenticated inventory and fresh quotes.",
            "Uncertain broker outcomes must be reconciled before any new order; never auto-retry.",
        ],
    }
