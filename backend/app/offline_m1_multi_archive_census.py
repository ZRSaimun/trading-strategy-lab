"""Disconnected aggregation of previously generated exploratory M1 archive receipts."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
import re

BODY_KEYS = (
    "policy", "source", "bar_count", "bar_manifest_sha256",
    "timestamp_discontinuities", "backward_jumps", "adjacent_duplicates",
    "sweep_count", "ambiguous_count", "confirmed_count",
    "censored_gap_or_end", "excluded_overlap", "horizon_minutes",
    "roundtrip_cost_bps", "development_exploratory",
    "later_exploratory_not_holdout", "all_exploratory",
)
COSTS = (0, 5, 10, 20)
POLICY = "exploratory-sweep20-mss3-fvg2-window5-nextopen-15m-v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Finite numeric receipt field required")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Nonfinite receipt field")
    return result


def _check(report):
    if not isinstance(report, dict) or type(report.get("research_schema_version")) is not int or report["research_schema_version"] != 1:
        raise ValueError("Expected original M1 research schema v1")
    if report.get("policy") != POLICY or type(report.get("horizon_minutes")) is not int or report["horizon_minutes"] != 15:
        raise ValueError("Frozen rule mismatch")
    if (not isinstance(report.get("roundtrip_cost_bps"), list)
            or len(report["roundtrip_cost_bps"]) != len(COSTS)
            or any(type(x) is not int or x != expected for x, expected in zip(report["roundtrip_cost_bps"], COSTS))):
        raise ValueError("Cost grid mismatch")
    if any(report.get(k) is not False for k in (
        "trade_authorized", "verified_profitability", "protected_holdout",
        "source_authenticity_verified", "executable_quotes_verified",
        "financing_modeled", "market_calendar_verified",
    )) or report.get("research_only") is not True:
        raise ValueError("Only non-executing unverified research receipts accepted")
    src = report.get("source")
    if not isinstance(src, dict) or any(
        not isinstance(src.get(k), str) or not IDENT.fullmatch(src[k])
        for k in ("instrument", "provider")
    ) or src.get("price_side") != "UNVERIFIED_SINGLE_SIDE" or src.get("time_convention") != "SOURCE_WALL_UNVERIFIED":
        raise ValueError("Source identity or epistemic status mismatch")
    for sha in (src.get("archive_sha256"), report.get("bar_manifest_sha256"), report.get("research_sha256")):
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError("Invalid receipt SHA-256")
    if any(k not in report for k in BODY_KEYS):
        raise ValueError("Missing research hash body")
    expected = hashlib.sha256(_canonical({k: report[k] for k in BODY_KEYS}).encode()).hexdigest()
    if expected != report["research_sha256"]:
        raise ValueError("Research receipt fingerprint mismatch")
    counts = ("bar_count", "confirmed_count", "censored_gap_or_end", "excluded_overlap")
    if any(type(report.get(k)) is not int or report[k] < 0 for k in counts) or report["bar_count"] == 0:
        raise ValueError("Invalid population counts")
    s = report.get("all_exploratory")
    if not isinstance(s, dict) or type(s.get("count")) is not int or s["count"] < 0:
        raise ValueError("Invalid evaluated population")
    if s["count"] + report["censored_gap_or_end"] + report["excluded_overlap"] != report["confirmed_count"]:
        raise ValueError("Signal population does not reconcile")
    if s["count"] == 0:
        if s.get("mean_gross_bps") is not None or any(
            s.get("mean_net_bps_by_roundtrip_cost", {}).get(str(c)) is not None for c in COSTS
        ):
            raise ValueError("Empty receipt must have unknown performance")
        return src, 0, None
    gross = _number(s.get("mean_gross_bps"))
    net = s.get("mean_net_bps_by_roundtrip_cost")
    if not isinstance(net, dict) or set(net) != {str(c) for c in COSTS}:
        raise ValueError("Incomplete cost scenarios")
    for cost in COSTS:
        if abs(_number(net[str(cost)]) - (gross - cost)) > Decimal("0.000002"):
            raise ValueError("Net cost scenario does not reconcile")
    return src, s["count"], gross


def audit_m1_multi_archive_census(reports):
    """Summarize immutable self-hashed reports; hashes do not authenticate archives."""
    if not isinstance(reports, (list, tuple)) or not 2 <= len(reports) <= 64:
        raise ValueError("Expected 2..64 bounded original research reports")
    seen_archives, seen_manifests = set(), set()
    groups = defaultdict(list)
    for report in reports:
        src, count, gross = _check(report)
        archive_sha = src["archive_sha256"]
        manifest_sha = report["bar_manifest_sha256"]
        if archive_sha in seen_archives or manifest_sha in seen_manifests:
            raise ValueError("Duplicate original archive or identical candle manifest")
        seen_archives.add(archive_sha)
        seen_manifests.add(manifest_sha)
        groups[(src["instrument"], src["provider"])].append((archive_sha, count, gross))
    result = []
    for (instrument, provider), entries in sorted(groups.items()):
        entries.sort(key=lambda x: x[0])
        count = sum(x[1] for x in entries)
        mean = sum((x[2] * x[1] for x in entries if x[2] is not None), Decimal(0)) / count if count else None

        def rounded(value):
            return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)) if value is not None else None

        result.append({
            "instrument": instrument, "provider": provider,
            "archive_count": len(entries), "evaluated_count": count,
            "weighted_mean_gross_bps_rounded_receipts": rounded(mean),
            "weighted_mean_net_bps_by_illustrative_cost": {
                str(cost): rounded(mean - cost) if mean is not None else None for cost in COSTS
            },
            "all_nonempty_archives_negative_at_5bps": (
                all(gross is not None and gross < 5 for _, _, gross in entries)
                if count and all(n > 0 for _, n, _ in entries) else None
            ),
            "archive_sha256": [sha for sha, _, _ in entries],
        })
    body = {"policy": POLICY, "cost_grid_bps": list(COSTS), "report_count": len(reports), "groups": result}
    return {**body, "research_sha256": hashlib.sha256(_canonical(body).encode()).hexdigest(),
            "research_only": True, "trade_authorized": False,
            "verified_profitability": False, "protected_holdout": False,
            "source_authenticity_verified": False, "executable_quotes_verified": False,
            "warning": "Self-hashed declarations are not authenticated vendor evidence. Means are weighted from six-decimal rounded per-archive reports; no raw execution receipts, financing, verified UTC, protected holdout or trade permission."}
