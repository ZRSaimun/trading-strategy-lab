"""Process-death recovery checks for the disconnected, caller-declared demo journal.

A separate Python process is killed with os._exit at real SQLite write boundaries.
This tests process termination and SQLite transaction recovery, NOT power loss,
storage-controller durability, broker authenticity or permission to trade.
"""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from app.offline_demo_order_receipt_replay import fingerprint_demo_order_event
from app.offline_demo_receipt_sqlite_journal import (
    append_declared_demo_receipt_snapshot as append,
    read_declared_demo_receipt_journal_head as read,
)

ZERO = "0" * 64
IDENTITY = ("provider", "venue", "account_alias", "instrument", "client_order_id")

# Executed in an independent interpreter so os._exit never kills pytest.
# The proxy delegates all SQLite operations and terminates only after the
# specified real SQL statement executes (except before_commit).
_WORKER = r"""
import json
import os
import sys
from app import offline_demo_receipt_sqlite_journal as journal

request = json.loads(sys.stdin.read())
phase = request["phase"]
original_open = journal._open

def intercepted_open(path, *, writable):
    connection = original_open(path, writable=writable)
    if not writable:
        return connection

    class CrashProxy:
        def execute(self, statement, *args):
            normalized = statement.strip().upper()
            if phase == "before_commit" and normalized == "COMMIT":
                os._exit(73)
            result = connection.execute(statement, *args)
            if phase == "after_snapshot_insert" and normalized.startswith(
                "INSERT INTO DEMO_ORDER_SNAPSHOTS"
            ):
                os._exit(71)
            if phase == "after_head_update" and normalized.startswith(
                "UPDATE DEMO_ORDER_JOURNAL SET"
            ):
                os._exit(72)
            if phase == "after_commit" and normalized == "COMMIT":
                os._exit(74)
            return result

        def __getattr__(self, name):
            return getattr(connection, name)

    return CrashProxy()

journal._open = intercepted_open
journal.append_declared_demo_receipt_snapshot(
    request["path"], request["scope"], request["events"],
    request["manifest"], request["expected_previous"],
)
# Reaching this line means the test did not hit its intended crash boundary.
sys.exit(89)
"""

EXIT = {
    "after_snapshot_insert": 71,
    "after_head_update": 72,
    "before_commit": 73,
    "after_commit": 74,
}


def payload(*, as_of=200, extra_fill=False):
    scope = {
        "provider": "Synthetic", "venue": "DEMO",
        "account_alias": "crash-test-account", "instrument": "XAUUSD-CFD",
        "client_order_id": "crash-test-order", "side": "BUY",
        "requested_contracts": 5, "submitted_at_ms": 100,
        "as_of_ms": as_of, "intent_sha256": "a" * 64,
    }
    specs = [
        ("SUBMITTED", 100, 101, 0, None),
        ("ACCEPTED", 110, 111, 0, "broker-1"),
        ("FILL", 120, 121, 2, "broker-1"),
    ]
    if extra_fill:
        specs.append(("FILL", 220, 221, 1, "broker-1"))
    events = []
    previous = ZERO
    for sequence, (kind, occurred, received, contracts, broker) in enumerate(specs, 1):
        event = {
            "sequence": sequence, "event_id": f"event-{sequence}",
            "kind": kind, "occurred_at_ms": occurred,
            "received_at_ms": received, "broker_order_id": broker,
            "contracts": contracts, "receipt_sha256": f"{sequence:064x}",
            "previous_event_sha256": previous,
            **{name: scope[name] for name in IDENTITY},
        }
        events.append(event)
        previous = fingerprint_demo_order_event(scope, event)
    manifest = {
        "expected_event_count": len(events),
        "expected_head_sha256": previous,
        "manifest_recorded_at_ms": events[-1]["received_at_ms"],
    }
    return scope, events, manifest


def die_during_append(path, data, prior, phase):
    request = {
        "path": str(path), "scope": data[0], "events": data[1],
        "manifest": data[2], "expected_previous": prior, "phase": phase,
    }
    completed = subprocess.run(
        [sys.executable, "-c", _WORKER],
        input=json.dumps(request), text=True, capture_output=True,
        timeout=15, check=False,
    )
    assert completed.returncode == EXIT[phase], (
        f"Expected deliberate process exit {EXIT[phase]}, got "
        f"{completed.returncode}; stderr={completed.stderr[-2000:]}"
    )


def assert_sqlite_consistent(path, *, expected_rows):
    with sqlite3.connect(path, timeout=5) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT count(*) FROM demo_order_snapshots"
        ).fetchone()[0] == expected_rows
        assert connection.execute(
            "SELECT count(*) FROM demo_order_journal"
        ).fetchone()[0] == (1 if expected_rows else 0)


@pytest.mark.parametrize("phase", tuple(EXIT))
def test_crash_during_genesis_recovers_atomically(tmp_path, phase):
    path = tmp_path / "genesis.sqlite"
    first = payload()
    die_during_append(path, first, ZERO, phase)
    committed = phase == "after_commit"
    assert_sqlite_consistent(path, expected_rows=1 if committed else 0)

    if committed:
        observed = read(path, first[0])
        assert observed["revision"] == 1
        assert observed["declared_filled_contracts"] == 2
        retry = append(path, *first, ZERO)
        assert retry["status"] == "IDEMPOTENT_DECLARED_RETRY"
        assert retry["checkpoint_sha256"] == observed["checkpoint_sha256"]
    else:
        with pytest.raises(ValueError, match="No matching"):
            read(path, first[0])
        retry = append(path, *first, ZERO)
        assert retry["status"] == "DECLARED_SNAPSHOT_LOCALLY_COMMITTED"
        assert retry["revision"] == 1
    assert_sqlite_consistent(path, expected_rows=1)
    assert not retry["may_execute_demo_order"]
    assert not retry["may_execute_real_order"]
    assert not retry["broker_receipts_authenticated"]


@pytest.mark.parametrize("phase", tuple(EXIT))
def test_crash_during_second_snapshot_preserves_cas_and_exposure(tmp_path, phase):
    path = tmp_path / "append.sqlite"
    first = payload()
    initial = append(path, *first, ZERO)
    later = payload(as_of=400, extra_fill=True)
    die_during_append(path, later, initial["checkpoint_sha256"], phase)

    committed = phase == "after_commit"
    assert_sqlite_consistent(path, expected_rows=2 if committed else 1)
    observed = read(path, first[0])
    assert observed["revision"] == (2 if committed else 1)
    assert observed["declared_filled_contracts"] == (3 if committed else 2)
    assert observed["declared_remaining_contracts"] == (2 if committed else 3)

    retry = append(path, *later, initial["checkpoint_sha256"])
    if committed:
        assert retry["status"] == "IDEMPOTENT_DECLARED_RETRY"
        assert retry["checkpoint_sha256"] == observed["checkpoint_sha256"]
    else:
        assert retry["status"] == "DECLARED_SNAPSHOT_LOCALLY_COMMITTED"
        assert retry["revision"] == 2
    final = read(path, later[0])
    assert final["revision"] == 2
    assert final["declared_filled_contracts"] == 3
    assert final["declared_remaining_contracts"] == 2
    assert_sqlite_consistent(path, expected_rows=2)
    assert not final["broker_population_complete"]
    assert final["manual_broker_reconciliation_required"]
    assert not final["may_execute_real_order"]
