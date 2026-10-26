"""Synthetic normalized export fixtures; not genuine broker evidence."""
from copy import deepcopy
import csv
import hashlib
import io
import random

import pytest

from app.offline_broker_export_preflight import preflight_normalized_broker_export, _COLUMNS


def fixture():
    def row(seq, kind, **changes):
        d = dict(sequence=str(seq), event_id=f"event{seq}", kind=kind,
                 provider="Synthetic", venue="DEMO", account_alias="test",
                 instrument="XAUUSD-CFD", position_id="position1", order_id="order1",
                 currency="USD", source_ref=f"ref{seq}", effective_at_ms=str(100+seq),
                 posted_at_ms=str(200+seq), side="", quantity="", price="", signed_cash="")
        if kind == "FILL":
            d.update(side="BUY", quantity="2.5", price="4000.125")
        else:
            d.update(signed_cash="1.25")
        d.update(changes)
        return d
    return [row(1, "FILL"), row(2, "COMMISSION"), row(3, "FINANCING")]


def encode(rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def run(rows=None, *, data=None, **scope_changes):
    rows = fixture() if rows is None else rows
    data = encode(rows) if data is None else data
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="test",
                 currency="USD", export_id="export1", captured_at_ms=500,
                 evaluation_as_of_ms=600, expected_sha256=hashlib.sha256(data).hexdigest(),
                 expected_event_count=len(rows))
    scope.update(scope_changes)
    return preflight_normalized_broker_export(scope, data)


def test_valid_normalized_export_no_authentication_or_order_permission():
    out = run()
    assert out["event_count"] == 3
    assert out["kind_counts"] == {"ADJUSTMENT": 0, "COMMISSION": 1, "FILL": 1, "FINANCING": 1}
    assert out["declared_cash_by_kind"]["FINANCING"] == "1.25"
    assert out["declared_cash_by_kind"]["COMMISSION"] == "1.25"
    assert not out["authenticated_broker_source"]
    assert not out["independent_statement_completeness"]
    assert not out["may_execute_demo_order"]
    assert not out["may_execute_real_order"]
    assert not out["verified_profitability"]
    assert out == run()


@pytest.mark.parametrize("change", [
    {"sequence": "1"}, {"sequence": "4"}, {"event_id": "event1"},
    {"provider": "Other"}, {"venue": "LIVE"}, {"account_alias": "other"},
    {"currency": "GBP"}, {"kind": "FX"}, {"posted_at_ms": "501"},
    {"effective_at_ms": "999"}, {"posted_at_ms": "199"},
    {"source_ref": "=formula"}, {"instrument": ""}, {"position_id": ""},
    {"side": "BUY"}, {"quantity": "2"}, {"price": "2"},
    {"signed_cash": "1e3"}, {"signed_cash": "-0.00"},
])
def test_invalid_cash_event_fails_closed(change):
    rows = fixture()
    rows[1].update(change)
    with pytest.raises(ValueError):
        run(rows)


@pytest.mark.parametrize("change", [
    {"order_id": ""}, {"side": ""}, {"side": "SHORT"},
    {"quantity": "0"}, {"quantity": "-2"}, {"quantity": "1e3"},
    {"price": "0"}, {"price": "NaN"}, {"price": "-1"},
    {"signed_cash": "1.00"},
])
def test_invalid_fill_fails_closed(change):
    rows = fixture()
    rows[0].update(change)
    with pytest.raises(ValueError):
        run(rows)


def test_missing_declared_row_and_empty_statement_fail_closed():
    with pytest.raises(ValueError):
        run(fixture()[:2], expected_event_count=3)
    with pytest.raises(ValueError):
        run([], expected_event_count=0)


def test_missing_middle_sequence_fails_closed():
    rows = fixture()
    rows.pop(1)
    with pytest.raises(ValueError):
        run(rows)


def test_hash_tampering_and_bad_clock_fail_closed():
    with pytest.raises(ValueError):
        run(expected_sha256="0" * 64)
    with pytest.raises(ValueError):
        run(evaluation_as_of_ms=400, captured_at_ms=500)
    with pytest.raises(ValueError):
        run(captured_at_ms=202)


def test_malformed_headers_multiline_utf8_bom_and_binary_rejected():
    data = encode(fixture())
    for invalid in [data.replace(b"sequence,", b"seq,"), data + b"\n", b"\xef\xbb\xbf" + data,
                    data + b"\x00", data + b"\xff", data.replace(b"ref2", b'"ref\n2"')]:
        with pytest.raises(ValueError):
            run(data=invalid)


def test_strict_type_bounds_and_input_immutability():
    rows = fixture()
    original = deepcopy(rows)
    out = run(rows)
    assert rows == original
    out["events"][0]["price"] = "999999"
    assert rows == original
    with pytest.raises(ValueError):
        run(expected_event_count=True)
    with pytest.raises(ValueError):
        run(data=bytearray(encode(rows)))
    with pytest.raises(ValueError):
        run(data=b"X" * 2_000_001)


def test_signed_cash_is_exact_and_negative_credit_is_not_silently_absed():
    rows = fixture()
    rows[1]["signed_cash"] = "-2.50"
    rows[2]["signed_cash"] = "0.01"
    out = run(rows)
    assert out["declared_cash_by_kind"]["COMMISSION"] == "-2.50"
    assert out["declared_cash_by_kind"]["FINANCING"] == "0.01"


def test_200_randomized_valid_normalized_populations():
    rng = random.Random(7312)
    for _ in range(200):
        rows = fixture()
        for i, row in enumerate(rows):
            if row["kind"] != "FILL":
                cents = rng.randint(-100_000, 100_000)
                row["signed_cash"] = f"{cents / 100:.2f}"
        report = run(rows)
        assert report["event_count"] == len(rows)
        assert report["kind_counts"]["FILL"] == 1
        assert report["may_execute_real_order"] is False
