"""Read-only, offline reconciliation of a staged Twelve Data historical import.

Internal consistency only: not vendor authentication, licensing, backup validation,
an executable quote, a live-feed health check, or a production migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat

from .completed_candle_quality import assess_completed_m1
from .provider_snapshot import verify_normalized_snapshot


def reconcile_staging_dataset(manifest: dict, archive: bytes, candles: list[dict]) -> dict:
    """Compare a staged manifest, exact snapshot bytes, and persisted candle rows.

    Inputs must be obtained from the SAME isolated staging dataset. This function
    never connects to a database, network, broker, or filesystem.
    """
    if not isinstance(manifest, dict) or not isinstance(candles, list):
        raise ValueError("Expected a manifest object and candle list")
    expected = {
        "provider": "twelvedata",
        "provider_symbol": "XAU/USD",
        "hash_scope": "vetted source-field snapshot",
        "rights_confirmation_scope": "owner_assertion_only",
        "source": "Twelve Data · XAU/USD · historical API (rights unverified)",
        "volume_type": "none",
        "receipt_clock": "server_wall_utc",
        "elapsed_clock": "server_monotonic",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Manifest provider or provenance mismatch")
    if manifest.get("rights_confirmed") is not True:
        raise ValueError("Missing explicit owner rights assertion")
    if manifest.get("live") is not False:
        raise ValueError("Historical dataset must not claim to be live")
    for key in ("provider_instrument_entitlement_verified", "retention_rights_verified",
                "display_rights_verified", "non_display_rights_verified"):
        if manifest.get(key) is not False:
            raise ValueError("Unverified provider rights must remain explicit")
    for key in ("retrieved_at", "request_started_at", "response_received_at",
                "request_elapsed_ms", "request_limit", "rows", "start", "end",
                "gaps", "request_end"):
        if type(manifest.get(key)) is not int:
            raise ValueError("Missing or invalid integer manifest field")
    # These fields describe the server request, not a provider-signed timestamp.
    # Do not compare wall-clock duration to monotonic elapsed time: the server
    # clock can jump between request and receipt.
    if (manifest["request_started_at"] != manifest["retrieved_at"]
            or manifest["request_started_at"] < 60
            or manifest["request_elapsed_ms"] < 0
            or not 1 <= manifest["request_limit"] <= 5000
            or manifest["rows"] > manifest["request_limit"]
            or not 0 <= manifest["request_end"] <= manifest["request_started_at"] - 60):
        raise ValueError("Manifest request and receipt provenance mismatch")
    if not 1 <= len(candles) <= 5000 or manifest["rows"] != len(candles):
        raise ValueError("Persisted candle count mismatch")
    if not isinstance(archive, bytes) or not 0 < len(archive) <= 3_000_000:
        raise ValueError("Invalid historical archive bytes")
    digest = hashlib.sha256(archive).hexdigest()
    if manifest.get("sha256") != digest:
        raise ValueError("Archive SHA-256 does not match manifest")
    for candle in candles:
        if not isinstance(candle, dict):
            raise ValueError("Invalid stored candle row")
        if (candle.get("instrument") != "XAUUSD-TD"
                or candle.get("source") != manifest["source"]
                or candle.get("retrieved_at") != manifest["retrieved_at"]):
            raise ValueError("Stored candle provenance mismatch")
    verify_normalized_snapshot(candles, archive, "XAU/USD")
    quality = assess_completed_m1(candles, manifest["response_received_at"])
    if manifest.get("quality") != quality:
        raise ValueError("Stored candle quality report mismatch")
    if (manifest["start"] != candles[0]["time"]
            or manifest["end"] != candles[-1]["time"]
            or manifest["gaps"] != quality["observed_timestamp_gaps"]
            or manifest["request_end"] < candles[-1]["time"]):
        raise ValueError("Manifest range or observed-gap mismatch")
    return {
        "result": "INTERNAL_STAGING_CONSISTENCY_ONLY",
        "archive_sha256": digest,
        "observed_candles": len(candles),
        "observed_timestamp_gaps": quality["observed_timestamp_gaps"],
        "last_candle_close_utc": quality["last_candle_close_utc"],
        "provider_entitlement_verified": False,
        "source_authenticity_verified": False,
        "market_calendar_checked": False,
        "executable_bid_ask_verified": False,
        "live": False,
        "may_execute_order": False,
    }


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Nonstandard JSON numeric constant")


def _read_regular_bounded(path: str, limit: int) -> bytes:
    """Read only a bounded regular file; do not follow a final symlink or FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Input is not a bounded regular file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Input exceeds size limit")
        return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only offline staging reconciliation")
    parser.add_argument("--manifest", required=True, help="Staged manifest JSON path")
    parser.add_argument("--archive", required=True, help="Exact content-addressed snapshot path")
    parser.add_argument("--candles", required=True, help="Staged persisted-candle JSON array path")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(_read_regular_bounded(args.manifest, 200_000),
                              object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
        archive = _read_regular_bounded(args.archive, 3_000_000)
        candles = json.loads(_read_regular_bounded(args.candles, 2_000_000),
                             object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
        report = reconcile_staging_dataset(manifest, archive, candles)
    except (ValueError, OSError, TypeError, OverflowError, KeyError):
        print(json.dumps({"result": "REJECTED", "live": False, "may_execute_order": False}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
