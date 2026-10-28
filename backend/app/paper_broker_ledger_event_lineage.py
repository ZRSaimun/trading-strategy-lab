"""Offline, read-only ledger event lineage vs declared broker UNKNOWN intents.

This module never opens a ledger, authenticates a broker or releases quarantine.
Caller-supplied event rows and audit tips are untrusted even when self-consistent.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_MAX_EVENTS = 10_000
_MAX_MS = 8_640_000_000_000_000
_ZERO = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_BROKERS = frozenset({"PAPER-LOCAL", "T212-INVEST-DEMO", "T212-STOCKSISA-DEMO",
                      "T212-INVEST-LIVE", "T212-STOCKSISA-LIVE"})
_TERMINAL = frozenset({"RECONCILED_FILLED", "RECONCILED_REJECTED", "RECONCILED_CANCELLED"})
_EVENTS = _TERMINAL | {"PREPARED", "ATTEMPT_UNKNOWN"}
_KEYS = {"seq", "broker", "account", "order_id", "event", "evidence_sha",
         "recorded_at_ms", "prev_hash", "event_hash"}
_MAX_UNKNOWN_TO_ATTEMPT_MS = 60_000


def _digest(value: Any, name: str, *, zero_ok: bool = False) -> str:
    if type(value) is not str or not _SHA.fullmatch(value) or (not zero_ok and value == _ZERO):
        raise ValueError(f"Invalid {name}")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _ms(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {name}")
    return value


def _event_digest(seq: int, broker: str, account: str, order: str,
                  event: str, evidence: str, stamp: int, previous: str) -> str:
    """Exactly PR #148's reviewed v1 event-hash canonicalization."""
    payload = [1, seq, broker, account, order, event, evidence, stamp, previous]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def inspect_declared_ledger_event_lineage(expected: dict, ledger_summary: dict,
                                          events: list[dict],
                                          prior_ledger_tip_sha256: str) -> dict[str, Any]:
    """Rebuild the complete caller-declared v1 ledger and compare UNKNOWN intents.

    The event list must start at genesis, include every event in sequence and
    match the separately pinned tip. Invalid events raise ValueError (HOLD).
    A clean result is only an unauthenticated diagnostic, never clearance.
    """
    _digest(prior_ledger_tip_sha256, "prior ledger tip")
    if type(events) is not list or not 1 <= len(events) <= _MAX_EVENTS:
        raise ValueError("Invalid complete ledger event population")
    if type(expected) is not dict or type(ledger_summary) is not dict:
        raise ValueError("Invalid ledger comparison input")
    if ledger_summary.get("schema") != "paper-submission-attempt-ledger-v1":
        raise ValueError("Unsupported ledger schema")
    if (type(ledger_summary.get("event_count")) is not int
            or ledger_summary["event_count"] != len(events)):
        raise ValueError("Ledger event count does not match complete stream")
    expected_broker = _id(expected.get("broker"), "expected broker")
    expected_account = _id(expected.get("account_alias"), "expected account")
    if expected_broker not in _BROKERS:
        raise ValueError("Unsupported broker")
    expected_rows = expected.get("unresolved_orders")
    if type(expected_rows) is not list or not 1 <= len(expected_rows) <= 256:
        raise ValueError("Invalid expected unresolved population")
    expected_intents = {}
    for row in expected_rows:
        if type(row) is not dict:
            raise ValueError("Invalid expected order row")
        cid = _id(row.get("client_order_id"), "expected client order ID")
        if cid in expected_intents:
            raise ValueError("Duplicate expected order ID")
        expected_intents[cid] = (_digest(row.get("intent_sha"), "expected intent"),
                                 _ms(row.get("attempted_at_ms"), "expected attempt time"))

    state: dict[tuple[str, str, str], tuple[str, str, int | None]] = {}
    unresolved_accounts: dict[tuple[str, str], tuple[str, str, str]] = {}
    seen_intents: set[tuple[str, str, str]] = set()
    seen_receipts: set[tuple[str, str, str]] = set()
    previous = _ZERO
    last_time = -1
    for seq, row in enumerate(events, 1):
        if type(row) is not dict or set(row) != _KEYS:
            raise ValueError("Invalid ledger event schema")
        if type(row["seq"]) is not int or row["seq"] != seq:
            raise ValueError("Ledger event sequence gap/replay")
        broker = _id(row["broker"], "event broker")
        account = _id(row["account"], "event account")
        order = _id(row["order_id"], "event order")
        if broker not in _BROKERS:
            raise ValueError("Unsupported event broker")
        event = row["event"]
        if type(event) is not str or event not in _EVENTS:
            raise ValueError("Invalid ledger event transition")
        evidence = _digest(row["evidence_sha"], "event evidence")
        stamp = _ms(row["recorded_at_ms"], "event timestamp")
        prev = _digest(row["prev_hash"], "previous event hash", zero_ok=True)
        actual_hash = _digest(row["event_hash"], "event hash")
        if prev != previous or stamp < last_time:
            raise ValueError("Ledger hash chain or clock regression")
        if actual_hash != _event_digest(seq, broker, account, order, event,
                                        evidence, stamp, prev):
            raise ValueError("Ledger event hash mismatch")
        key = (broker, account, order)
        account_key = (broker, account)
        old = state.get(key)
        evidence_key = (broker, account, evidence)
        if event == "PREPARED":
            if old is not None or account_key in unresolved_accounts:
                raise ValueError("Duplicate preparation or unresolved account")
            if evidence_key in seen_intents or evidence_key in seen_receipts:
                raise ValueError("Reused intent or terminal receipt fingerprint")
            seen_intents.add(evidence_key)
            state[key] = (evidence, "PREPARED", None)
        elif event == "ATTEMPT_UNKNOWN":
            if (old is None or old[1] != "PREPARED" or old[0] != evidence
                    or account_key in unresolved_accounts):
                raise ValueError("Invalid or repeated UNKNOWN transition")
            state[key] = (evidence, "ATTEMPT_UNKNOWN", stamp)
            unresolved_accounts[account_key] = key
        else:
            if (old is None or old[1] != "ATTEMPT_UNKNOWN"
                    or unresolved_accounts.get(account_key) != key):
                raise ValueError("Invalid terminal transition")
            if evidence_key in seen_intents or evidence_key in seen_receipts:
                raise ValueError("Reused intent or terminal receipt as reconciliation")
            seen_receipts.add(evidence_key)
            state[key] = (old[0], event, old[2])
            del unresolved_accounts[account_key]
        previous = actual_hash
        last_time = stamp

    failures: set[str] = set()
    if previous != prior_ledger_tip_sha256 or previous != ledger_summary.get("audit_tip_sha256"):
        failures.add("ledger_event_tip_mismatch")
    if last_time != ledger_summary.get("last_recorded_at_ms"):
        failures.add("ledger_event_last_time_mismatch")
    if ledger_summary.get("order_count") != len(state):
        failures.add("ledger_event_order_count_mismatch")
    rows = ledger_summary.get("orders")
    if type(rows) is not list or len(rows) != len(state):
        failures.add("ledger_event_projection_mismatch")
    else:
        projection = {(b, a, o): status for (b, a, o), (_, status, _) in state.items()}
        declared = {}
        for row in rows:
            if type(row) is not dict or set(row) != {"broker", "account_alias", "client_order_id", "status"}:
                raise ValueError("Invalid declared ledger projection row")
            key = (_id(row["broker"], "projection broker"),
                   _id(row["account_alias"], "projection account"),
                   _id(row["client_order_id"], "projection order"))
            if key in declared:
                raise ValueError("Duplicate declared ledger projection row")
            declared[key] = row["status"]
        if projection != declared:
            failures.add("ledger_event_projection_mismatch")
    actual_unknown = {order: (digest, unknown_at)
                      for (broker, account, order), (digest, status, unknown_at) in state.items()
                      if (broker, account) == (expected_broker, expected_account)
                      and status == "ATTEMPT_UNKNOWN"}
    if set(actual_unknown) != set(expected_intents):
        failures.add("ledger_event_unknown_population_mismatch")
    for order, (intent, attempt_at) in expected_intents.items():
        if order not in actual_unknown:
            continue
        ledger_intent, unknown_at = actual_unknown[order]
        if ledger_intent != intent:
            failures.add("ledger_event_intent_mismatch")
        if (unknown_at is None or not unknown_at <= attempt_at
                or attempt_at - unknown_at > _MAX_UNKNOWN_TO_ATTEMPT_MS):
            failures.add("ledger_unknown_attempt_time_mismatch")
    return {
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_EVENT_LINEAGE_CANDIDATE_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "event_count": len(events),
        "reconstructed_order_count": len(state),
        "ledger_authenticated": False,
        "ledger_tip_custody_authenticated": False,
        "broker_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }


def inspect_declared_ledger_event_inventory_bridge(
    expected: dict, snapshots: list[dict], check_times_ms: list[int],
    prior_snapshot_digests: list[str], prior_chain_digest: str,
    prior_context_digest: str, ledger_summary: dict,
    prior_ledger_tip_sha256: str, events: list[dict],
    max_checkpoint_gap_ms: int = 60_000,
) -> dict[str, Any]:
    """Compose existing snapshot/context/ledger checks with full event lineage."""
    from app.paper_broker_ledger_inventory_bridge import inspect_declared_ledger_inventory_bridge
    prior = inspect_declared_ledger_inventory_bridge(
        expected, snapshots, check_times_ms, prior_snapshot_digests,
        prior_chain_digest, prior_context_digest, ledger_summary,
        prior_ledger_tip_sha256, max_checkpoint_gap_ms=max_checkpoint_gap_ms)
    lineage = inspect_declared_ledger_event_lineage(
        expected, ledger_summary, events, prior_ledger_tip_sha256)
    failures = sorted(set(prior["failed_checks"]) | set(lineage["failed_checks"]))
    return {
        **prior,
        "status": ("HOLD_RECONCILIATION" if failures
                   else "DECLARED_LEDGER_EVENT_INVENTORY_CANDIDATE_UNVERIFIED"),
        "failed_checks": failures,
        "ledger_intent_fingerprints_bound": False,
        "declared_ledger_intent_lineage_matches": not failures,
        "ledger_authenticated": False,
        "broker_authenticated": False,
        "may_clear_unknown": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
