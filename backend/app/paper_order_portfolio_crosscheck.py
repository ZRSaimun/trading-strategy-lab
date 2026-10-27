"""Cross-check a hypothetical order review against one declared PAPER portfolio.

This is an offline, zero-side-effect consistency bridge, NOT a risk release
or broker verification. It cannot reserve orders, approve them, or send them.
"""
from decimal import Decimal
import hashlib
import json

from app.live_order_review import build_review_packet
from app.paper_group_concentration_guard import evaluate_grouped_paper_exposure

_SCHEMA = "paper-order-portfolio-crosscheck-v1"
_NUMERIC_ROW = {
    "quantity": "quantity",
    "entry_price": "entry_price",
    "stop_price": "stop_price",
    "stressed_exit_price": "stressed_exit_price",
    "point_value_cash": "point_value_cash",
    "estimated_total_cost_cash": "estimated_total_cost_cash",
    "margin_rate_percent": "margin_rate_percent",
    "quote_bid": "bid",
    "quote_ask": "ask",
}
_NUMERIC_ACCOUNT = {
    "account_equity_cash": "equity_cash",
    "daily_realized_pnl_cash": "daily_realized_pnl_cash",
    "daily_unrealized_pnl_cash": "daily_unrealized_pnl_cash",
    "max_position_loss_cash": "max_position_loss_cash",
    "max_daily_loss_cash": "max_daily_loss_cash",
    "max_gross_leverage": "max_gross_leverage",
    "max_spread_bps": "max_spread_bps",
}


def _sum_details(details, field):
    return sum((Decimal(item[field]) for item in details), Decimal("0"))


def evaluate_paper_order_portfolio_crosscheck(
    order: dict, account_snapshot: dict, group_policy: dict, *, now_ms: int
) -> dict:
    """Re-evaluate BOTH guards on the same clock and bind their assumptions.

    The candidate must appear exactly once as PENDING in the complete declared
    exposure list. Other exposure reservations must match the single-order
    review exactly, rather than trusting a caller's lower totals. Every check
    remains unauthenticated and the final status is always HOLD_RECONCILIATION.
    """
    review = build_review_packet(
        order, now_ms=now_ms, max_quote_age_ms=3000,
        max_transport_lag_ms=1000,
    )
    portfolio = evaluate_grouped_paper_exposure(
        account_snapshot, group_policy, now_ms=now_ms,
    )
    candidates = [
        (i, row) for i, row in enumerate(account_snapshot["exposures"])
        if row["client_order_id"] == order["client_order_id"]
    ]
    index, candidate = candidates[0] if len(candidates) == 1 else (None, None)
    checks = {}
    checks["candidate_exactly_once_and_pending"] = (
        candidate is not None and candidate["state"] == "PENDING"
    )
    checks["account_identity_and_currency"] = (
        order["account_alias"] == account_snapshot["account_id"]
        and order["currency"] == account_snapshot["currency"]
    )
    checks["candidate_source_and_side"] = (
        candidate is not None
        and order["instrument"] == candidate["instrument"]
        and order["quote_provider"] == candidate["provider"]
        and order["venue"] == candidate["venue"]
        and (("LONG" if order["direction"] == "BUY" else "SHORT")
             == candidate["side"])
    )
    checks["candidate_quote_identity_fields"] = (
        candidate is not None
        and all(
            order[order_field] == candidate[row_field]
            for order_field, row_field in (
                ("quote_observed_at_ms", "quote_observed_at_ms"),
                ("quote_received_at_ms", "quote_received_at_ms"),
            )
        )
    )
    checks["candidate_prices_quantity_and_costs"] = (
        candidate is not None
        and all(
            Decimal(order[order_field]) == Decimal(candidate[row_field])
            for order_field, row_field in _NUMERIC_ROW.items()
        )
    )
    checks["account_risk_policy_and_pnl"] = all(
        Decimal(order[order_field]) == Decimal(account_snapshot[snapshot_field])
        for order_field, snapshot_field in _NUMERIC_ACCOUNT.items()
    )
    equity = Decimal(account_snapshot["equity_cash"])
    checks["independent_conservative_policy_ceiling"] = (
        account_snapshot["max_quote_age_ms"] <= 3000
        and account_snapshot["max_transport_lag_ms"] <= 1000
        and Decimal(account_snapshot["max_spread_bps"]) <= Decimal("100")
        and Decimal(account_snapshot["max_gross_leverage"]) <= Decimal("5")
        and Decimal(account_snapshot["max_position_loss_cash"]) <= equity * Decimal("0.05")
        and Decimal(account_snapshot["max_daily_loss_cash"]) <= equity * Decimal("0.10")
    )
    # The account guard calculates full downside on all OPEN, PENDING and
    # uncertain rows, with adverse executable-side stress. Never let the
    # single-order packet omit or undercount that declared existing inventory.
    other_details = [
        detail for i, detail in enumerate(portfolio["exposures"])
        if i != index
    ]
    checks["other_notional_margin_and_risk_reconciled"] = (
        candidate is not None
        and Decimal(order["existing_gross_notional_cash"])
        == _sum_details(other_details, "gross_notional_cash")
        and Decimal(order["existing_reserved_margin_cash"])
        == _sum_details(other_details, "assumed_margin_cash")
        and Decimal(order["existing_reserved_risk_cash"])
        == _sum_details(other_details, "stressed_loss_cash")
    )
    checks["candidate_stress_not_understated"] = (
        candidate is not None
        and Decimal(portfolio["exposures"][index]["stressed_loss_cash"])
        >= Decimal(review["stressed_loss_cash"])
    )
    checks["both_guards_structurally_pass"] = (
        review["assumption_checks_pass"]
        and portfolio["status"] == "ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED"
        and not portfolio["failed_checks"]
    )
    failures = sorted(
        ["crosscheck." + name for name, passed in checks.items() if not passed]
        + ["review." + name for name in review["failed_checks"]]
        + ["portfolio." + name for name in portfolio["failed_checks"]]
    )
    # A diagnostic fingerprint is NOT a signature, broker receipt, approval,
    # one-time nonce or authenticated audit record. Do not persist raw inputs.
    digest = hashlib.sha256(json.dumps({
        "schema": _SCHEMA,
        "order": order,
        "account_snapshot": account_snapshot,
        "group_policy": group_policy,
        "now_ms": now_ms,
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {
        "schema": _SCHEMA,
        "status": "HOLD_RECONCILIATION",
        "structural_checks_pass": not failures,
        "checks": checks,
        "failed_checks": failures,
        "review_sha256": review["review_sha256"],
        "crosscheck_sha256": digest,
        "candidate_stressed_loss_cash": (
            portfolio["exposures"][index]["stressed_loss_cash"]
            if candidate is not None else None
        ),
        "portfolio_stressed_equity_cash": portfolio["stressed_equity_cash"],
        "quote_authenticated": False,
        "account_authenticated": False,
        "inventory_complete_verified": False,
        "broker_stop_acknowledged": False,
        "risk_reservation_committed": False,
        "owner_approval_verified": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warnings": [
            "Both guards consume caller-declared inputs, not authenticated broker evidence.",
            "Matching snapshots do not establish complete inventory, stop fills or quote provenance.",
            "No persistent ID reservation, durable kill-switch transaction or owner approval is performed.",
            "Never use this fingerprint or a structural pass to submit a paper or real order.",
        ],
    }
