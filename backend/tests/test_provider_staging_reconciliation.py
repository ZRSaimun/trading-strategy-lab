"""Entirely synthetic offline staging reconciliation tests; no network or DB."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.completed_candle_quality import assess_completed_m1
from app.provider_staging_reconciliation import main, reconcile_staging_dataset


def fixture_data():
    source = "Twelve Data · XAU/USD · historical API (rights unverified)"
    candles = [
        dict(instrument="XAUUSD-TD", time=60, open=100.0, high=102.0,
             low=99.0, close=101.0, volume=None, source=source, retrieved_at=240),
        dict(instrument="XAUUSD-TD", time=180, open=101.0, high=103.0,
             low=100.0, close=102.0, volume=None, source=source, retrieved_at=240),
    ]
    archive = json.dumps({
        "meta": {"symbol": "XAU/USD", "interval": "1min", "exchange_timezone": "UTC"},
        "values": [
            {"time": "1970-01-01T00:01:00+00:00", "open": "100",
             "high": "102", "low": "99", "close": "101"},
            {"time": "1970-01-01T00:03:00+00:00", "open": "101",
             "high": "103", "low": "100", "close": "102"},
        ],
    }, separators=(",", ":")).encode()
    manifest = {
        "provider": "twelvedata", "provider_symbol": "XAU/USD",
        "hash_scope": "vetted source-field snapshot",
        "rights_confirmation_scope": "owner_assertion_only",
        "source": source, "retrieved_at": 240, "request_started_at": 240,
        "response_received_at": 300, "request_elapsed_ms": 42,
        "receipt_clock": "server_wall_utc", "elapsed_clock": "server_monotonic",
        "request_limit": 2, "request_end": 180, "rows": 2,
        "start": 60, "end": 180, "gaps": 1, "volume_type": "none",
        "rights_confirmed": True,
        "sha256": hashlib.sha256(archive).hexdigest(),
        "quality": assess_completed_m1(candles, 300),
        "provider_instrument_entitlement_verified": False,
        "retention_rights_verified": False, "display_rights_verified": False,
        "non_display_rights_verified": False, "live": False,
    }
    return manifest, archive, candles


def test_consistent_staging_inputs_report_only_internal_consistency():
    manifest, archive, candles = fixture_data()
    original = deepcopy((manifest, archive, candles))
    report = reconcile_staging_dataset(manifest, archive, candles)
    assert report["result"] == "INTERNAL_STAGING_CONSISTENCY_ONLY"
    assert report["observed_candles"] == 2
    assert report["observed_timestamp_gaps"] == 1
    assert report["archive_sha256"] == manifest["sha256"]
    assert not report["live"] and not report["may_execute_order"]
    assert not report["provider_entitlement_verified"]
    assert (manifest, archive, candles) == original


@pytest.mark.parametrize("change", [
    lambda m, a, c: m.update(sha256="0" * 64),
    lambda m, a, c: m.update(rows=1),
    lambda m, a, c: m.update(start=120),
    lambda m, a, c: m.update(end=240),
    lambda m, a, c: m.update(gaps=0),
    lambda m, a, c: m.update(request_end=120),
    lambda m, a, c: m.update(response_received_at=240),
    lambda m, a, c: m.update(request_started_at=241),
    lambda m, a, c: m.update(request_elapsed_ms=-1),
    lambda m, a, c: m.update(request_elapsed_ms="42"),
    lambda m, a, c: m.update(request_limit=1),
    lambda m, a, c: m.update(request_limit=True),
    lambda m, a, c: m.update(request_end=181),
    lambda m, a, c: m.update(receipt_clock="provider_clock"),
    lambda m, a, c: m.update(elapsed_clock="server_wall_utc"),
    lambda m, a, c: m.update(volume_type="tick"),
    lambda m, a, c: m.update(rights_confirmed=False),
    lambda m, a, c: m.update(live=True),
    lambda m, a, c: m.update(provider_instrument_entitlement_verified=True),
    lambda m, a, c: m.update(rights_confirmation_scope="provider_verified"),
    lambda m, a, c: m["quality"].update(observed_timestamp_gaps=0),
    lambda m, a, c: c[0].update(close=101.5),
    lambda m, a, c: c[0].update(source="unknown source"),
    lambda m, a, c: c[0].update(instrument="XAGUSD-TD"),
    lambda m, a, c: c[0].update(retrieved_at=241),
    lambda m, a, c: c.reverse(),
])
def test_tampered_staging_evidence_fails_closed(change):
    manifest, archive, candles = fixture_data()
    change(manifest, archive, candles)
    with pytest.raises(ValueError):
        reconcile_staging_dataset(manifest, archive, candles)


def test_relabeling_both_manifest_and_rows_does_not_rewrite_source_identity():
    manifest, archive, candles = fixture_data()
    manifest["source"] = "Unverified replacement source"
    for row in candles:
        row["source"] = manifest["source"]
    with pytest.raises(ValueError, match="provenance"):
        reconcile_staging_dataset(manifest, archive, candles)


def test_changed_archive_bytes_fail_even_when_stored_rows_unchanged():
    manifest, archive, candles = fixture_data()
    with pytest.raises(ValueError, match="SHA-256"):
        reconcile_staging_dataset(manifest, archive + b" ", candles)


def test_cli_offline_success_only_emits_non_executable_summary(tmp_path, capsys):
    manifest, archive, candles = fixture_data()
    paths = [tmp_path / n for n in ("manifest.json", "snapshot.json", "candles.json")]
    paths[0].write_text(json.dumps(manifest))
    paths[1].write_bytes(archive)
    paths[2].write_text(json.dumps(candles))
    assert main(["--manifest", str(paths[0]), "--archive", str(paths[1]),
                 "--candles", str(paths[2])]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "INTERNAL_STAGING_CONSISTENCY_ONLY"
    assert result["may_execute_order"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in paths)


def test_cli_rejects_symlink_input_without_following_it(tmp_path, capsys):
    manifest, archive, candles = fixture_data()
    paths = [tmp_path / n for n in ("manifest.json", "snapshot.json", "candles.json")]
    paths[0].write_text(json.dumps(manifest))
    paths[1].write_bytes(archive)
    paths[2].write_text(json.dumps(candles))
    link = tmp_path / "alias.json"
    link.symlink_to(paths[1])
    assert main(["--manifest", str(paths[0]), "--archive", str(link),
                 "--candles", str(paths[2])]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "result": "REJECTED", "live": False, "may_execute_order": False
    }


def test_cli_rejects_ambiguous_duplicate_manifest_json(tmp_path, capsys):
    manifest, archive, candles = fixture_data()
    paths = [tmp_path / n for n in ("manifest.json", "snapshot.json", "candles.json")]
    raw = json.dumps(manifest)
    paths[0].write_text(raw.replace('"provider":', '"provider":"untrusted","provider":', 1))
    paths[1].write_bytes(archive)
    paths[2].write_text(json.dumps(candles))
    assert main(["--manifest", str(paths[0]), "--archive", str(paths[1]),
                 "--candles", str(paths[2])]) == 2
    assert json.loads(capsys.readouterr().out)["result"] == "REJECTED"
