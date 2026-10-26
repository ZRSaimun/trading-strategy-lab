"""Disconnected account-equity drawdown and margin-buffer review.

Caller-declared checkpoints are NOT broker-authenticated. This module has no
network access, persistence, order sender, or execution authorization.
"""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re

_MAX_MS = 8_640_000_000_000_000
_MAX_SEQ = 2**53 - 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z")
_POLICY_FIELDS = frozenset({
    "account_alias", "provider", "currency", "max_peak_drawdown_pct",
    "max_intraday_drawdown_pct", "min_free_equity_pct", "max_consecutive_losses",
})
_SNAPSHOT_FIELDS = frozenset({
    "account_alias", "provider", "currency", "sequence", "observed_ms",
    "received_ms", "utc_day", "balance_cash", "unrealized_pnl_cash",
    "equity_cash", "used_margin_cash", "reserved_risk_cash",
    "peak_equity_cash", "day_start_equity_cash", "consecutive_losses",
})
_MONEY = (
    "balance_cash", "unrealized_pnl_cash", "equity_cash",
    "used_margin_cash", "reserved_risk_cash", "peak_equity_cash",
    "day_start_equity_cash",
)


def _decimal(value, label, *, allow_negative=False):
    if not isinstance(value, str) or not _CASH.fullmatch(value):
        raise ValueError(f"{label}: expected bounded decimal string")
    number = Decimal(value)
    if not number.is_finite() or (number < 0 and not allow_negative):
        raise ValueError(f"{label}: invalid amount")
    return number


def _identity(value, label):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label}: invalid identity")
    return value


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Invalid UTC day")
    try:
        if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
            raise ValueError("Invalid UTC day")
    except ValueError as exc:
        raise ValueError("Invalid UTC day") from exc
    return value


def _snapshot(value):
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_FIELDS:
        raise ValueError("Incomplete account checkpoint")
    s = dict(value)
    for key in ("account_alias", "provider", "currency"):
        s[key] = _identity(s[key], key)
    if not re.fullmatch(r"[A-Z]{3}", s["currency"]):
        raise ValueError("Invalid currency")
    for key in ("sequence", "observed_ms", "received_ms", "consecutive_losses"):
        upper = _MAX_SEQ if key in ("sequence", "consecutive_losses") else _MAX_MS
        if type(s[key]) is not int or not 0 <= s[key] <= upper:
            raise ValueError(f"{key}: invalid integer")
    if s["sequence"] == 0:
        raise ValueError("Sequence must be positive")
    s["utc_day"] = _day(s["utc_day"])
    for key in _MONEY:
        s[key] = _decimal(s[key], key, allow_negative=key == "unrealized_pnl_cash")
    if (s["equity_cash"] <= 0 or s["peak_equity_cash"] <= 0
            or s["day_start_equity_cash"] <= 0):
        raise ValueError("Nonpositive equity baseline")
    return s


def _policy(value):
    if not isinstance(value, dict) or set(value) != _POLICY_FIELDS:
        raise ValueError("Incomplete drawdown policy")
    p = dict(value)
    for key in ("account_alias", "provider", "currency"):
        p[key] = _identity(p[key], key)
    if not re.fullmatch(r"[A-Z]{3}", p["currency"]):
        raise ValueError("Invalid currency")
    for key in ("max_peak_drawdown_pct", "max_intraday_drawdown_pct",
                "min_free_equity_pct"):
        p[key] = _decimal(p[key], key)
    if not (0 < p["max_peak_drawdown_pct"] <= 20
            and 0 < p["max_intraday_drawdown_pct"] <= 10
            and 10 <= p["min_free_equity_pct"] <= 100):
        raise ValueError("Unsafe declared drawdown/margin policy")
    if (type(p["max_consecutive_losses"]) is not int
            or not 1 <= p["max_consecutive_losses"] <= 10):
        raise ValueError("Invalid loss-streak threshold")
    return p


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    return value


def review_paper_account_drawdown(policy, current, *, now_ms, previous=None,
                                  max_snapshot_age_ms=3000,
                                  max_transport_lag_ms=1000):
    """Read-only structural review. A passing result is NEVER permission to trade."""
    if type(now_ms) is not int or not 0 <= now_ms <= _MAX_MS:
        raise ValueError("Invalid server clock")
    if (type(max_snapshot_age_ms) is not int
            or not 100 <= max_snapshot_age_ms <= 3000
            or type(max_transport_lag_ms) is not int
            or not 0 <= max_transport_lag_ms <= 1000):
        raise ValueError("Unsafe snapshot freshness policy")
    p = _policy(policy)
    c = _snapshot(current)
    old = _snapshot(previous) if previous is not None else None
    checks = {}
    checks["account_identity_matches"] = all(
        c[k] == p[k] and (old is None or old[k] == p[k])
        for k in ("account_alias", "provider", "currency")
    )
    checks["prior_checkpoint_present"] = old is not None
    checks["sequence_contiguous"] = bool(old is not None
                                         and c["sequence"] == old["sequence"] + 1)
    checks["observation_monotonic"] = bool(old is not None
        and old["observed_ms"] < c["observed_ms"]
        and old["received_ms"] <= c["observed_ms"]
        and old["received_ms"] < c["received_ms"])
    checks["same_utc_day"] = bool(old is not None
                                 and c["utc_day"] == old["utc_day"])
    checks["day_start_not_reset"] = bool(old is not None
        and c["day_start_equity_cash"] == old["day_start_equity_cash"])
    checks["peak_not_reset"] = bool(old is not None
                                   and c["peak_equity_cash"] >= old["peak_equity_cash"])
    checks["loss_streak_not_reset_without_receipt"] = bool(old is not None
        and c["consecutive_losses"] >= old["consecutive_losses"])
    checks["checkpoint_equity_reconciles"] = all(
        s["balance_cash"] + s["unrealized_pnl_cash"] == s["equity_cash"]
        for s in (c,) if s is not None
    ) and (old is None or
           old["balance_cash"] + old["unrealized_pnl_cash"] == old["equity_cash"])
    checks["baselines_cover_observed_equity"] = all(
        s["peak_equity_cash"] >= max(s["equity_cash"], s["day_start_equity_cash"])
        for s in (c, old) if s is not None
    )
    checks["snapshot_time_order"] = (
        c["observed_ms"] <= c["received_ms"] <= now_ms
        and (old is None or old["observed_ms"] <= old["received_ms"] <= now_ms)
    )
    checks["snapshot_fresh"] = (checks["snapshot_time_order"]
                               and now_ms - c["observed_ms"] <= max_snapshot_age_ms)
    checks["transport_lag_ok"] = (checks["snapshot_time_order"]
        and c["received_ms"] - c["observed_ms"] <= max_transport_lag_ms)
    checks["utc_day_matches_observation"] = (
        datetime.fromtimestamp(c["observed_ms"] // 1000, tz=timezone.utc)
        .date().isoformat() == c["utc_day"]
        and (old is None or
             datetime.fromtimestamp(old["observed_ms"] // 1000, tz=timezone.utc)
             .date().isoformat() == old["utc_day"])
    )
    with localcontext() as ctx:
        ctx.prec = 80
        peak_loss = max(Decimal(0), c["peak_equity_cash"] - c["equity_cash"])
        day_loss = max(Decimal(0), c["day_start_equity_cash"] - c["equity_cash"])
        peak_stressed_pct = ((peak_loss + c["reserved_risk_cash"])
                             * 100 / c["peak_equity_cash"])
        day_stressed_pct = ((day_loss + c["reserved_risk_cash"])
                            * 100 / c["day_start_equity_cash"])
        free_cash = c["equity_cash"] - c["used_margin_cash"] - c["reserved_risk_cash"]
        free_pct = free_cash * 100 / c["equity_cash"]
    checks["peak_drawdown_within_cap"] = peak_stressed_pct < p["max_peak_drawdown_pct"]
    checks["intraday_drawdown_within_cap"] = day_stressed_pct < p["max_intraday_drawdown_pct"]
    checks["margin_buffer_within_policy"] = (
        free_cash > 0 and free_pct >= p["min_free_equity_pct"])
    checks["loss_streak_below_threshold"] = (
        c["consecutive_losses"] < p["max_consecutive_losses"])
    digest_input = _canonical({
        "schema": "paper-account-drawdown-review-v1", "policy": p,
        "previous": old, "current": c, "now_ms": now_ms,
        "max_snapshot_age_ms": max_snapshot_age_ms,
        "max_transport_lag_ms": max_transport_lag_ms,
    })
    fingerprint = hashlib.sha256(json.dumps(
        digest_input, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("ascii")).hexdigest()
    return {
        "schema": "paper-account-drawdown-review-v1",
        "status": "HOLD_RECONCILIATION",
        "checks": checks,
        "failed_checks": [key for key, ok in checks.items() if not ok],
        "assumption_checks_pass": all(checks.values()),
        "stressed_peak_drawdown_pct": format(peak_stressed_pct, "f"),
        "stressed_intraday_drawdown_pct": format(day_stressed_pct, "f"),
        "free_equity_cash": format(free_cash, "f"),
        "free_equity_pct": format(free_pct, "f"),
        "review_sha256": fingerprint,
        "account_authenticated": False,
        "checkpoint_authenticated": False,
        "owner_approval_recorded": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warning": (
            "Caller-declared equity, peak, day start and risk reservations are "
            "unauthenticated. A digest is not a signature or broker receipt; "
            "gaps, fees, FX and liquidation can exceed modeled stress. "
            "Day rollover or loss-streak reset requires external reconciliation."
        ),
    }
