"""Disconnected account/quote snapshot freshness and revision fence.

Caller-declared evidence only: NEVER broker authentication or order permission.
"""
from __future__ import annotations

from typing import Any
from decimal import Decimal
import re

_MAX_MS = 8_640_000_000_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_DEC = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_BROKERS = frozenset({"PAPER-LOCAL", "T212-INVEST-DEMO", "T212-STOCKSISA-DEMO",
                      "T212-INVEST-LIVE", "T212-STOCKSISA-LIVE"})
_ACCOUNT_FIELDS = frozenset({
    "broker", "account_alias", "equity", "free_margin", "daily_realized_pnl",
    "open_notional", "open_risk", "circuit_breaker_open",
})
_QUOTE_FIELDS = frozenset({
    "instrument", "source", "bid", "ask", "observed_at_ms", "received_at_ms",
})
_SNAPSHOT_FIELDS = frozenset({
    "account", "risk_quote", "revision", "session_epoch", "positions_revision",
    "orders_revision", "observed_at_ms", "received_at_ms",
    "positions_synced_at_ms", "orders_synced_at_ms", "reconciliation_complete",
    "unresolved_attempts",
})
_POLICY_FIELDS = frozenset({
    "max_account_age_ms", "max_account_transport_lag_ms",
    "max_quote_account_skew_ms", "max_positions_sync_age_ms",
    "max_orders_sync_age_ms",
})
# Local diagnostic ceilings, not broker guarantees or approved trading limits.
_POLICY_CEILINGS = {
    "max_account_age_ms": 3000,
    "max_account_transport_lag_ms": 1000,
    "max_quote_account_skew_ms": 1000,
    "max_positions_sync_age_ms": 3000,
    "max_orders_sync_age_ms": 3000,
}


def _object(value: Any, fields: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"Invalid {label} schema")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0,
             maximum: int = _MAX_MS) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid {label}")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _decimal(value: Any, label: str, *, signed: bool = False,
             positive: bool = False) -> Decimal:
    if type(value) is not str or not (_SIGNED if signed else _DEC).fullmatch(value):
        raise ValueError(f"Invalid {label}")
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError(f"Invalid {label}")
    return number


def _account(raw: Any, label: str) -> dict:
    a = _object(raw, _ACCOUNT_FIELDS, label)
    if _identifier(a["broker"], label + " broker") not in _BROKERS:
        raise ValueError("Unsupported broker account label")
    _identifier(a["account_alias"], label + " alias")
    for key in ("equity", "free_margin", "open_notional", "open_risk"):
        _decimal(a[key], label + " " + key, positive=key == "equity")
    _decimal(a["daily_realized_pnl"], label + " daily P&L", signed=True)
    if type(a["circuit_breaker_open"]) is not bool:
        raise ValueError("Invalid account circuit breaker")
    return a


def _quote(raw: Any, label: str) -> dict:
    q = _object(raw, _QUOTE_FIELDS, label)
    _identifier(q["instrument"], label + " instrument")
    _identifier(q["source"], label + " source")
    bid = _decimal(q["bid"], label + " bid", positive=True)
    ask = _decimal(q["ask"], label + " ask", positive=True)
    if ask <= bid:
        raise ValueError("Invalid crossed or locked quote")
    for key in ("observed_at_ms", "received_at_ms"):
        _integer(q[key], label + " " + key)
    return q


def _typed_equal(a: Any, b: Any) -> bool:
    """Unlike dict equality, do not confuse True with 1 or 1 with 1.0."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_typed_equal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def _snapshot(raw: Any, label: str) -> dict:
    s = _object(raw, _SNAPSHOT_FIELDS, label)
    _account(s["account"], label + " account")
    _quote(s["risk_quote"], label + " quote")
    for key in ("revision", "positions_revision", "orders_revision"):
        _integer(s[key], label + " " + key)
    _integer(s["session_epoch"], label + " session_epoch", minimum=1)
    _integer(s["unresolved_attempts"], label + " unresolved_attempts", maximum=10000)
    for key in ("observed_at_ms", "received_at_ms", "positions_synced_at_ms", "orders_synced_at_ms"):
        _integer(s[key], label + " " + key)
    if type(s["reconciliation_complete"]) is not bool:
        raise ValueError("Invalid reconciliation_complete")
    return s


def inspect_declared_account_snapshot_fence(
    account: dict, risk_quote: dict, current_snapshot: dict,
    previous_snapshot: dict | None, policy: dict, now_ms: int,
) -> dict[str, Any]:
    """Check caller-declared account freshness, continuity and quote binding.

    Invalid schemas raise ValueError; suspect evidence returns HOLD. A clean
    declared snapshot is still NOT authenticated, reserved or executable.
    """
    a = _account(account, "risk account")
    q = _quote(risk_quote, "risk quote")
    now = _integer(now_ms, "evaluation time")
    p = _object(policy, _POLICY_FIELDS, "freshness policy")
    for key, ceiling in _POLICY_CEILINGS.items():
        _integer(p[key], key, minimum=1, maximum=ceiling)
    s = _snapshot(current_snapshot, "current snapshot")
    prior = None if previous_snapshot is None else _snapshot(previous_snapshot, "previous snapshot")
    failures: set[str] = set()
    if not _typed_equal(s["account"], a):
        failures.add("risk_account_snapshot_mismatch")
    if not _typed_equal(s["risk_quote"], q):
        failures.add("risk_quote_snapshot_mismatch")
    observed, received = s["observed_at_ms"], s["received_at_ms"]
    if not observed <= received <= now or now - observed > p["max_account_age_ms"]:
        failures.add("stale_or_future_account_snapshot")
    if not observed <= received <= now or received - observed > p["max_account_transport_lag_ms"]:
        failures.add("account_transport_lag")
    quote_observed, quote_received = q["observed_at_ms"], q["received_at_ms"]
    if not quote_observed <= quote_received <= now:
        failures.add("invalid_quote_chronology")
    # Account/quote skew alone does not enforce quote freshness: a quote can
    # trail a fresh account by the entire allowed skew. Apply the same strict
    # age and transport ceilings to the bound quote, independently of any
    # caller-declared multi-feed or order-risk diagnostic.
    if quote_observed > now or now - quote_observed > p["max_account_age_ms"]:
        failures.add("stale_or_future_risk_quote")
    if quote_received < quote_observed or quote_received - quote_observed > p["max_account_transport_lag_ms"]:
        failures.add("risk_quote_transport_lag")
    if abs(quote_observed - observed) > p["max_quote_account_skew_ms"]:
        failures.add("quote_account_time_skew")
    for label in ("positions", "orders"):
        synced = s[label + "_synced_at_ms"]
        if synced > observed or synced > now or now - synced > p["max_" + label + "_sync_age_ms"]:
            failures.add("stale_or_future_" + label + "_sync")
    if a["circuit_breaker_open"]:
        failures.add("account_circuit_breaker_open")
    if not s["reconciliation_complete"]:
        failures.add("account_reconciliation_incomplete")
    if s["unresolved_attempts"]:
        failures.add("unresolved_order_attempts")
    if prior is not None:
        if not _typed_equal(s["account"]["broker"], prior["account"]["broker"]) or not _typed_equal(
            s["account"]["account_alias"], prior["account"]["account_alias"]
        ):
            failures.add("account_identity_changed")
        # A newer caller-declared envelope must not erase unresolved risk or
        # release a safety latch without independently verified reconciliation.
        # This also applies to callers using the standalone snapshot fence.
        if prior["account"]["circuit_breaker_open"] and not a["circuit_breaker_open"]:
            failures.add("circuit_breaker_reset_requires_external_evidence")
        if prior["unresolved_attempts"] > s["unresolved_attempts"]:
            failures.add("unknown_attempt_reduction_requires_external_evidence")
        if not prior["reconciliation_complete"] and s["reconciliation_complete"]:
            failures.add("reconciliation_release_requires_external_evidence")
        if s["session_epoch"] == prior["session_epoch"]:
            # A changed inventory cannot claim a new revision while reusing
            # its old sync timestamp. Revision-only heartbeat updates with
            # unchanged financial payloads remain diagnostic, not authority.
            if (s["positions_revision"] > prior["positions_revision"]
                    and s["positions_synced_at_ms"] <= prior["positions_synced_at_ms"]
                    and any(Decimal(a[k]) != Decimal(prior["account"][k])
                            for k in ("open_notional", "open_risk"))):
                failures.add("positions_changed_without_new_sync")
            if (s["orders_revision"] > prior["orders_revision"]
                    and s["orders_synced_at_ms"] <= prior["orders_synced_at_ms"]
                    and s["unresolved_attempts"] != prior["unresolved_attempts"]):
                failures.add("unknown_attempts_changed_without_new_orders_sync")
            if (s["positions_revision"] == prior["positions_revision"]
                    and any(Decimal(a[k]) != Decimal(prior["account"][k])
                            for k in ("open_notional", "open_risk"))):
                failures.add("positions_changed_without_revision")
            if (s["orders_revision"] == prior["orders_revision"]
                    and s["unresolved_attempts"] != prior["unresolved_attempts"]):
                failures.add("unknown_attempts_changed_without_orders_revision")
        if s["session_epoch"] < prior["session_epoch"]:
            failures.add("session_epoch_rollback")
        elif s["session_epoch"] > prior["session_epoch"]:
            failures.add("session_change_requires_external_reconciliation")
        else:
            if s["revision"] <= prior["revision"]:
                failures.add("account_revision_replay")
            if s["positions_revision"] < prior["positions_revision"]:
                failures.add("positions_revision_rollback")
            if s["orders_revision"] < prior["orders_revision"]:
                failures.add("orders_revision_rollback")
        if observed <= prior["observed_at_ms"] or received < prior["received_at_ms"]:
            failures.add("snapshot_time_replay")
        # A later account envelope must not conceal an older positions/orders
        # inventory snapshot. A repeated sync timestamp is permitted because
        # an unchanged inventory can legitimately be reused while still fresh.
        # On session changes the separate reconciliation hold already applies.
        if s["session_epoch"] == prior["session_epoch"]:
            for label in ("positions", "orders"):
                if s[label + "_synced_at_ms"] < prior[label + "_synced_at_ms"]:
                    failures.add(label + "_sync_time_rollback")
            # A primary quote can be reused at the same timestamp within its
            # freshness window, but a *backward* quote timestamp is suspect.
            previous_quote = prior["risk_quote"]
            if (q["instrument"], q["source"]) == (previous_quote["instrument"], previous_quote["source"]):
                if q["observed_at_ms"] < previous_quote["observed_at_ms"]:
                    failures.add("quote_observation_time_rollback")
                if q["received_at_ms"] < previous_quote["received_at_ms"]:
                    failures.add("quote_receipt_time_rollback")
                # A quote observed at the same instant cannot silently acquire
                # different prices merely by advancing its account envelope.
                if (q["observed_at_ms"] == previous_quote["observed_at_ms"]
                        and (q["bid"], q["ask"]) != (previous_quote["bid"], previous_quote["ask"])):
                    failures.add("quote_payload_changed_without_new_observation")
            elif q["instrument"] == previous_quote["instrument"]:
                # Switching the claimed primary source would otherwise evade
                # same-source timestamp and payload continuity checks.
                failures.add("quote_source_change_requires_external_evidence")
            else:
                # This single-primary-quote snapshot cannot independently
                # verify a different instrument's continuity. A new symbol
                # must not be used to bypass same-stream replay protection.
                failures.add("quote_instrument_change_requires_external_evidence")
    return {
        "status": "HOLD_ACCOUNT_SNAPSHOT_REVIEW" if failures else "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED",
        "failed_checks": sorted(failures),
        "broker_authenticated": False,
        "account_authenticated": False,
        "quote_authenticated": False,
        "external_reconciliation_verified": False,
        "atomic_reservation_verified": False,
        "stop_guaranteed": False,
        "requires_individual_owner_approval": True,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
