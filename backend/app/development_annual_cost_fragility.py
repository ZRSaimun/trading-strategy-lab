"""Offline, declared-only development annual cost and downside fragility audit.

No market data, validation/holdout outcomes, broker calls, or order routes.
An input SHA is a caller declaration, not an authenticated source or precommitment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?\Z")
_POS = re.compile(r"(?:[1-9]|10)(?:\.[0-9]{1,2})?\Z")
_SOURCE = {"provider", "venue", "instrument", "quote_side", "timezone", "account_alias", "settlement_currency", "archive_sha256"}
_PARTITION = {"registered_at", "development_end", "validation_start", "holdout_start", "embargo_seconds"}
_MANIFEST = {"source", "partition", "candidates", "folds"}
_FOLD = {"fold_id", "year", "train_start", "train_end", "test_start", "test_end", "train_label_available_at", "test_label_available_at"}
_TRIAL = {"candidate_id", "fold_id", "source_sha256", "gross_cash", "spread_cash", "slippage_cash", "commission_cash", "financing_cash", "fx_cash", "observed_at", "receipt_sha256"}
_CHARGES = ("spread_cash", "slippage_cash", "commission_cash", "fx_cash")
_MAX_TIME = 8640000000


def _exact(obj, fields, what):
    if type(obj) is not dict or set(obj) != fields:
        raise ValueError(f"Invalid {what} schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _time(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _money(value, *, nonnegative=False):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact monetary amount")
    number = Decimal(value)
    if (nonnegative and number < 0) or (value.startswith("-0") and number == 0):
        raise ValueError("Invalid signed monetary amount")
    return number


def _fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _fmt(number):
    return format(number.quantize(Decimal("0.01")), ".2f")


def _year(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).year


def _validate_manifest(manifest):
    _exact(manifest, _MANIFEST, "development manifest")
    source, part = manifest["source"], manifest["partition"]
    _exact(source, _SOURCE, "source identity")
    _exact(part, _PARTITION, "partition")
    for field in ("provider", "venue", "instrument", "account_alias"):
        if not _id(source[field]):
            raise ValueError("Invalid source identity")
    if source["quote_side"] not in ("BID", "ASK", "MID") or source["timezone"] != "UTC":
        raise ValueError("Unverified quote side or timestamp convention")
    if type(source["settlement_currency"]) is not str or _CCY.fullmatch(source["settlement_currency"]) is None or not _sha(source["archive_sha256"]):
        raise ValueError("Invalid source currency or archive digest")
    if not all(_time(part[k]) for k in ("registered_at", "development_end", "validation_start", "holdout_start")):
        raise ValueError("Invalid partition clocks")
    if not part["registered_at"] < part["development_end"] < part["validation_start"] < part["holdout_start"]:
        raise ValueError("Invalid development/validation/holdout partition order")
    if type(part["embargo_seconds"]) is not int or not 1 <= part["embargo_seconds"] <= 2592000:
        raise ValueError("Invalid embargo")
    candidates = manifest["candidates"]
    if type(candidates) is not list or not 2 <= len(candidates) <= 32 or any(not _id(c) for c in candidates) or candidates != sorted(set(candidates)):
        raise ValueError("Candidates must be a complete sorted unique declaration")
    folds = manifest["folds"]
    if type(folds) is not list or not 3 <= len(folds) <= 128:
        raise ValueError("Invalid bounded fold population")
    prev_end, seen, years = -1, set(), set()
    for fold in folds:
        _exact(fold, _FOLD, "fold")
        fid = fold["fold_id"]
        if not _id(fid) or fid in seen:
            raise ValueError("Invalid or duplicate fold ID")
        seen.add(fid)
        if not all(_time(fold[k]) for k in ("train_start", "train_end", "test_start", "test_end", "train_label_available_at", "test_label_available_at")):
            raise ValueError("Invalid fold clock")
        if not (part["registered_at"] < fold["train_start"] < fold["train_end"] and
                fold["train_end"] + part["embargo_seconds"] <= fold["test_start"] < fold["test_end"] <= part["development_end"] and
                fold["test_start"] >= prev_end and
                fold["train_start"] <= fold["train_label_available_at"] <= fold["train_end"] and
                fold["test_end"] <= fold["test_label_available_at"] <= part["development_end"]):
            raise ValueError("Overlapping, leaking, or out-of-development fold")
        if type(fold["year"]) is not int or fold["year"] != _year(fold["test_start"]) or fold["year"] != _year(fold["test_end"] - 1):
            raise ValueError("Fold year does not match UTC test interval")
        years.add(fold["year"])
        prev_end = fold["test_end"]
    if len(years) < 3:
        raise ValueError("At least three distinct development years required")
    return candidates, folds, years


def audit_development_annual_cost_fragility(manifest, trials, expected_manifest_sha256, *, adverse_multiplier="2"):
    """Compute paired annual/cost/downside diagnostics without reading holdouts.

    Requires exact candidate × fold population, same declared source, explicit
    cost fields, and after-fold observation timestamps. No order permission.
    """
    candidates, folds, years = _validate_manifest(manifest)
    digest = _fingerprint(manifest)
    if not _sha(expected_manifest_sha256) or expected_manifest_sha256 != digest:
        raise ValueError("Development manifest digest mismatch")
    if type(adverse_multiplier) is not str or _POS.fullmatch(adverse_multiplier) is None:
        raise ValueError("Invalid bounded adverse multiplier")
    multiplier = Decimal(adverse_multiplier)
    if multiplier < 1 or multiplier > 10:
        raise ValueError("Adverse multiplier must be >= 1")
    if type(trials) is not list or len(trials) != len(candidates) * len(folds):
        raise ValueError("Missing or extra candidate × fold trial population")
    fold_by_id = {f["fold_id"]: f for f in folds}
    population = {}
    receipts = set()
    with localcontext() as ctx:
        ctx.prec = 80
        for row in trials:
            _exact(row, _TRIAL, "trial")
            cid, fid = row["candidate_id"], row["fold_id"]
            key = (cid, fid)
            if cid not in candidates or fid not in fold_by_id or key in population:
                raise ValueError("Unknown or duplicate candidate/fold trial")
            if row["source_sha256"] != manifest["source"]["archive_sha256"]:
                raise ValueError("Cross-source trial evidence")
            if not _sha(row["receipt_sha256"]) or row["receipt_sha256"] in receipts:
                raise ValueError("Invalid or duplicate trial receipt identity")
            receipts.add(row["receipt_sha256"])
            if not _time(row["observed_at"]) or not (fold_by_id[fid]["test_label_available_at"] <= row["observed_at"] <= manifest["partition"]["development_end"]):
                raise ValueError("Future/early trial receipt or holdout leakage")
            gross = _money(row["gross_cash"])
            costs = sum((_money(row[k], nonnegative=True) for k in _CHARGES), Decimal(0))
            financing = _money(row["financing_cash"])
            baseline = gross - costs - financing
            # Credits are removed, not increased, in the adverse scenario.
            adverse_financing = financing * multiplier if financing > 0 else Decimal(0)
            adverse = gross - costs * multiplier - adverse_financing
            if adverse > baseline:
                raise ValueError("Adverse execution assumptions improved net")
            population[key] = (baseline, adverse)
        if len(population) != len(candidates) * len(folds):
            raise ValueError("Incomplete paired trial census")
        ordered = sorted(trials, key=lambda x: (x["candidate_id"], x["fold_id"]))
        summaries = {}
        for cid in candidates:
            running = peak = drawdown = Decimal(0)
            annual = {year: Decimal(0) for year in sorted(years)}
            baseline_total = adverse_total = Decimal(0)
            worst_fold = None
            for fold in folds:
                base, stress = population[(cid, fold["fold_id"])]
                baseline_total += base
                adverse_total += stress
                annual[fold["year"]] += base
                running += base
                peak = max(peak, running)
                drawdown = max(drawdown, peak - running)
                worst_fold = base if worst_fold is None else min(worst_fold, base)
            summaries[cid] = {
                "baseline_net_cash": _fmt(baseline_total),
                "adverse_net_cash": _fmt(adverse_total),
                "max_chronological_drawdown_cash": _fmt(drawdown),
                "worst_fold_net_cash": _fmt(worst_fold),
                "annual_net_cash": {str(year): _fmt(annual[year]) for year in sorted(years)},
            }
        def winner(excluded_year=None):
            return sorted(candidates, key=lambda c: (
                -sum((population[(c, f["fold_id"])][0] for f in folds if f["year"] != excluded_year), Decimal(0)), c
            ))[0]
        selected = winner()
        leave_out = {str(y): winner(y) for y in sorted(years)}
        return {
            "protocol": "development-annual-cost-fragility-v1",
            "status": "DECLARED_DEVELOPMENT_ONLY",
            "manifest_sha256": digest,
            "post_outcome_receipts_sha256": _fingerprint(ordered),
            "adverse_multiplier": adverse_multiplier,
            "fold_count": len(folds), "year_count": len(years), "candidate_count": len(candidates),
            "candidate_summaries": summaries,
            "baseline_development_winner": selected,
            "leave_one_year_out_winners": leave_out,
            "winner_changes_with_year_removal": any(v != selected for v in leave_out.values()),
            "source_authenticated": False,
            "pre_outcome_registration_verified": False,
            "independent_holdout_verified": False,
            "real_costs_verified": False,
            "verified_profitability": False,
            "may_execute_demo_order": False,
            "may_execute_real_order": False,
            "warning": "Synthetic/caller-declared fold P&L, costs, timestamps, and SHA identities are not authenticated; this is descriptive development-only risk research, not a holdout test or profit claim.",
        }
