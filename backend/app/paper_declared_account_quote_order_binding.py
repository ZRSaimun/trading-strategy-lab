"""Fail-closed composition of caller-declared quote, order and account evidence.

Read-only research preflight. No broker access, risk reservation or execution.
"""
from __future__ import annotations

from typing import Any

from app.paper_declared_account_snapshot_fence import inspect_declared_account_snapshot_fence
from app.paper_declared_quote_risk_binding import inspect_declared_quote_risk_binding


def inspect_declared_account_quote_order_binding(
    order: dict, risk_quote: dict, account: dict, risk_policy: dict,
    recent_orders: list[dict], primary_source: str, quote_sources: list[dict],
    consensus_policy: dict, current_snapshot: dict, previous_snapshot: dict | None,
    snapshot_policy: dict, now_ms: int,
) -> dict[str, Any]:
    """Compose all three disconnected diagnostics without granting permission.

    The previous snapshot is required for this stricter composite review, but
    caller-declared continuity is not proof of durable or authenticated state.
    Invalid input raises ValueError in the underlying strict validators.
    """
    quote_risk = inspect_declared_quote_risk_binding(
        order, risk_quote, account, risk_policy, recent_orders,
        primary_source, quote_sources, consensus_policy, now_ms,
    )
    account_fence = inspect_declared_account_snapshot_fence(
        account, risk_quote, current_snapshot, previous_snapshot,
        snapshot_policy, now_ms,
    )
    failures: set[str] = set()
    if quote_risk["failed_checks"]:
        failures.add("quote_risk_binding_hold")
    if account_fence["failed_checks"]:
        failures.add("account_snapshot_fence_hold")
    if previous_snapshot is None:
        failures.add("missing_prior_account_snapshot")
    else:
        prior = previous_snapshot
        current = current_snapshot
        if prior["account"]["circuit_breaker_open"] and not current["account"]["circuit_breaker_open"]:
            failures.add("circuit_breaker_reset_requires_external_evidence")
        if prior["unresolved_attempts"] > current["unresolved_attempts"]:
            failures.add("unknown_attempt_reduction_requires_external_evidence")
        if not prior["reconciliation_complete"] and current["reconciliation_complete"]:
            failures.add("reconciliation_release_requires_external_evidence")
        if current["session_epoch"] == prior["session_epoch"]:
            if (current["positions_revision"] == prior["positions_revision"] and
                    any(current["account"][k] != prior["account"][k]
                        for k in ("open_notional", "open_risk"))):
                failures.add("positions_changed_without_revision")
            if (current["orders_revision"] == prior["orders_revision"] and
                    current["unresolved_attempts"] != prior["unresolved_attempts"]):
                failures.add("unknown_attempts_changed_without_orders_revision")
    # A declared account/inventory policy must not silently be looser than the
    # risk quote's freshness or transport ceilings used for the same decision.
    if snapshot_policy["max_account_age_ms"] > risk_policy["max_quote_age_ms"]:
        failures.add("weaker_account_freshness_policy")
    if snapshot_policy["max_account_transport_lag_ms"] > risk_policy["max_transport_lag_ms"]:
        failures.add("weaker_account_transport_policy")
    if snapshot_policy["max_quote_account_skew_ms"] > risk_policy["max_quote_age_ms"]:
        failures.add("weaker_quote_account_skew_policy")
    for name in ("positions", "orders"):
        if snapshot_policy["max_" + name + "_sync_age_ms"] > snapshot_policy["max_account_age_ms"]:
            failures.add("weaker_" + name + "_sync_policy")
    return {
        "status": ("HOLD_ACCOUNT_QUOTE_ORDER_BINDING" if failures
                   else "DECLARED_ACCOUNT_QUOTE_ORDER_UNVERIFIED"),
        "failed_checks": sorted(failures),
        "quote_risk_failed_checks": quote_risk["failed_checks"],
        "account_snapshot_failed_checks": account_fence["failed_checks"],
        "estimated_stop_loss_with_slippage": quote_risk["risk_estimated_stop_loss_with_slippage"],
        "broker_authenticated": False,
        "account_authenticated": False,
        "quote_authenticated": False,
        "source_independence_verified": False,
        "external_reconciliation_verified": False,
        "atomic_reservation_verified": False,
        "stop_guaranteed": False,
        "requires_individual_owner_approval": True,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
