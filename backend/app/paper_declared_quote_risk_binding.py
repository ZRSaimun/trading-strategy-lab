"""Offline fail-closed binding of declared order-risk and multi-feed quote evidence.

This module does not authenticate prices, authorize orders or send anything.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.paper_declared_order_risk_preview import inspect_declared_order_risk_preview
from app.paper_declared_quote_consensus import inspect_declared_quote_consensus

_QUOTE_FIELDS = frozenset({"source", "instrument", "bid", "ask", "observed_at_ms", "received_at_ms"})


def inspect_declared_quote_risk_binding(
    order: dict, risk_quote: dict, account: dict, risk_policy: dict,
    recent_orders: list[dict], primary_source: str, quote_sources: list[dict],
    consensus_policy: dict, now_ms: int,
) -> dict[str, Any]:
    """Require exact primary quote binding and non-weaker consensus limits.

    Both underlying validators run even when binding fails. Clean evidence
    remains unauthenticated, disconnected and NEVER authorizes execution.
    """
    risk = inspect_declared_order_risk_preview(
        order, risk_quote, account, risk_policy, recent_orders, now_ms
    )
    consensus = inspect_declared_quote_consensus(
        order["instrument"], primary_source, quote_sources, consensus_policy, now_ms
    )
    failures: set[str] = set()
    if risk_quote["source"] != primary_source:
        failures.add("risk_quote_not_primary_source")
    primary_rows = [q for q in quote_sources if q["source"] == primary_source]
    if len(primary_rows) != 1:
        failures.add("primary_quote_not_unique")
    else:
        primary = primary_rows[0]
        # Exact textual values avoid silently rounding/rebasing the quote used
        # for risk arithmetic; source and both timestamps must also match.
        if set(primary) != _QUOTE_FIELDS or set(risk_quote) != _QUOTE_FIELDS or any(
            type(primary[k]) is not type(risk_quote[k]) or primary[k] != risk_quote[k]
            for k in _QUOTE_FIELDS
        ):
            failures.add("risk_quote_primary_snapshot_mismatch")
    for risk_key, census_key in (
        ("max_quote_age_ms", "max_quote_age_ms"),
        ("max_transport_lag_ms", "max_transport_lag_ms"),
        ("max_spread_bps", "max_spread_bps"),
    ):
        if Decimal(str(consensus_policy[census_key])) > Decimal(str(risk_policy[risk_key])):
            failures.add("weaker_consensus_" + census_key)
    if risk["failed_checks"]:
        failures.add("risk_preview_hold")
    if consensus["failed_checks"]:
        failures.add("quote_consensus_hold")
    return {
        "status": "HOLD_QUOTE_RISK_BINDING" if failures else "DECLARED_QUOTE_RISK_BINDING_UNVERIFIED",
        "failed_checks": sorted(failures),
        "risk_failed_checks": risk["failed_checks"],
        "consensus_failed_checks": consensus["failed_checks"],
        "risk_estimated_stop_loss_with_slippage": risk["estimated_stop_loss_with_slippage"],
        "quote_authenticated": False,
        "broker_authenticated": False,
        "source_independence_verified": False,
        "atomic_reservation_verified": False,
        "stop_guaranteed": False,
        "requires_individual_owner_approval": True,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
