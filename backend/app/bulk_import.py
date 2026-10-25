"""Explicit, resumable, source-isolated HistData M1 archive ingestion.

This does NOT change the legacy /api/import replacement route. All writes are
confined to separate tables; only completed datasets are eligible for research.
Run on an authorised machine with licensed archives; no network/vendor calls.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile

from sqlalchemy import (BigInteger, Column, Float, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text, select, func)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()
datasets = Table("historical_datasets", metadata,
    Column("id", String(64), primary_key=True),
    Column("provider", String(80), nullable=False),
    Column("instrument", String(80), nullable=False),
    Column("format", String(16), nullable=False),
    Column("utc_offset_minutes", Integer, nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("archive_filename", String(255), nullable=False),
    Column("state", String(24), nullable=False),
    Column("seen", BigInteger, nullable=False, default=0),
    Column("accepted", BigInteger, nullable=False, default=0),
    Column("rejected", BigInteger, nullable=False, default=0),
    Column("zero_volume", BigInteger, nullable=False, default=0),
    Column("checkpoint_member", Integer, nullable=False, default=0),
    Column("checkpoint_line", BigInteger, nullable=False, default=0),
    Column("last_timestamp", BigInteger, nullable=True),
    Column("error", Text, nullable=True),
)
candles = Table("historical_candles", metadata,
    Column("dataset_id", String(64), ForeignKey("historical_datasets.id"), primary_key=True),
    Column("time", BigInteger, primary_key=True),
    Column("open", Float, nullable=False), Column("high", Float, nullable=False),
    Column("low", Float, nullable=False), Column("close", Float, nullable=False),
    Column("volume", Float, nullable=True),
    Column("source_member", String(255), nullable=False),
    Column("source_line", BigInteger, nullable=False),
)
issues = Table("historical_quarantine", metadata,
    Column("dataset_id", String(64), ForeignKey("historical_datasets.id"), primary_key=True),
    Column("member_index", Integer, primary_key=True),
    Column("line", BigInteger, primary_key=True),
    Column("reason", String(100), nullable=False),
    Column("sample", String(300), nullable=False),
)
Index("ix_historical_dataset_instrument", datasets.c.provider, datasets.c.instrument, datasets.c.state)


def create_schema(engine):
    """Explicit CLI/setup action; never invoked automatically at service startup."""
    metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Restrict the new tables to the server DB role, matching the app's
        # private-schema policy. Names are hardcoded from our metadata.
        with engine.begin() as connection:
            for table_name in ("historical_datasets", "historical_candles", "historical_quarantine"):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
                for role in ("PUBLIC", "anon", "authenticated"):
                    if role != "PUBLIC":
                        exists = connection.exec_driver_sql(
                            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).scalar()
                        if not exists:
                            continue
                    connection.exec_driver_sql(f"REVOKE ALL ON TABLE {table_name} FROM {role}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_row(row, file_format, offset):
    try:
        values = next(csv.reader([row], delimiter=";" if file_format == "ascii" else ","))
        if file_format == "ascii":
            if len(values) != 6:
                raise ValueError("expected 6 ASCII fields")
            dt = datetime.strptime(values[0], "%Y%m%d %H%M%S")
            nums = values[1:]
        else:
            if len(values) != 7:
                raise ValueError("expected 7 MetaTrader fields")
            dt = datetime.strptime(values[0] + " " + values[1], "%Y.%m.%d %H:%M")
            nums = values[2:]
        if dt.second != 0:
            raise ValueError("not a complete M1 timestamp")
        # Offset is UTC offset of *archive's clock*: -300 means UTC=local+5h.
        dt = dt.replace(tzinfo=timezone(timedelta(minutes=offset)))
        epoch = int(dt.timestamp())
        o, h, l, c, v = [float(item) for item in nums]
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            raise ValueError("nonfinite OHLCV")
        if l > min(o, c) or h < max(o, c) or l > h:
            raise ValueError("inconsistent OHLC")
        if v < 0:
            raise ValueError("negative volume")
        return {"time": epoch, "open": o, "high": h, "low": l,
                "close": c, "volume": v}
    except (ValueError, OverflowError, csv.Error) as exc:
        raise ValueError(str(exc)) from exc


def _bulk_insert(connection, rows, table):
    if not rows:
        return
    dialect = connection.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(table).on_conflict_do_nothing()
    elif dialect == "sqlite":
        stmt = sqlite_insert(table).on_conflict_do_nothing()
    else:
        raise ValueError("Only SQLite and PostgreSQL are supported")
    connection.execute(stmt, rows)


def _flush(engine, dataset_id, accepted, rejected, zero, member, line, latest, candle_batch, issue_batch):
    # Store checkpoint and its imported candles atomically. A crash before
    # commit replays the same rows safely on restart.
    with engine.begin() as connection:
        _bulk_insert(connection, candle_batch, candles)
        _bulk_insert(connection, issue_batch, issues)
        connection.execute(datasets.update().where(datasets.c.id == dataset_id).values(
            checkpoint_member=member, checkpoint_line=line,
            seen=datasets.c.seen + accepted + rejected,
            accepted=datasets.c.accepted + accepted,
            rejected=datasets.c.rejected + rejected,
            zero_volume=datasets.c.zero_volume + zero,
            last_timestamp=latest,
            state="IMPORTING", error=None))


def ingest(engine, path, *, instrument, provider, file_format="ascii",
           utc_offset_minutes=-300, rights_confirmed=False, chunk_rows=5000,
           max_members=48, max_uncompressed_bytes=2_000_000_000,
           max_rows_per_run=None, quarantine_limit=5000):
    """Import source-isolated rows with durable checkpoints; explicit owner action.

    max_rows_per_run is for cooperative/test pause after a committed chunk.
    Archive must remain byte-identical across resume operations.
    """
    if not rights_confirmed:
        raise ValueError("Owner must confirm dataset use rights")
    if not 1 <= chunk_rows <= 20000:
        raise ValueError("chunk_rows must be 1..20000")
    if file_format not in ("ascii", "mt"):
        raise ValueError("format must be ascii or mt")
    if not -840 <= utc_offset_minutes <= 840:
        raise ValueError("offset out of range")
    for label, value in (("instrument", instrument), ("provider", provider)):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            raise ValueError("Invalid " + label)
    path = Path(path)
    digest = sha256_file(path)
    identity = hashlib.sha256(json.dumps([provider, instrument, file_format,
                                          utc_offset_minutes, digest]).encode()).hexdigest()
    with ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")]
        if not members or len(archive.infolist()) > max_members or len(members) > max_members:
            raise ValueError("archive has no CSV members or exceeds member limit")
        if any(m.flag_bits & 1 for m in members):
            raise ValueError("encrypted member not supported")
        if any(m.file_size > max_uncompressed_bytes for m in members) or sum(m.file_size for m in members) > max_uncompressed_bytes:
            raise ValueError("archive uncompressed size exceeds configured limit")
        # Requires schema installation (reviewed separately), never creates
        # tables or touches the legacy candles/records tables.
        with engine.begin() as connection:
            old = connection.execute(select(datasets).where(datasets.c.id == identity)).mappings().first()
            if old is None:
                connection.execute(datasets.insert().values(
                    id=identity, provider=provider, instrument=instrument,
                    format=file_format, utc_offset_minutes=utc_offset_minutes,
                    archive_sha256=digest, archive_filename=path.name[:255],
                    state="IMPORTING", seen=0, accepted=0, rejected=0,
                    zero_volume=0, checkpoint_member=0, checkpoint_line=0))
            elif old["state"] == "READY":
                # Older imports could label an archive READY after dropping bad rows.
                # Never affirm such a partial series as research-complete.
                if old["rejected"] != 0 or old["accepted"] <= 0 or old["seen"] != old["accepted"]:
                    raise ValueError("Existing READY archive has rejected or incomplete rows; research blocked")
                return {"dataset_id": identity, "state": "READY", "already_complete": True,
                        "accepted": old["accepted"], "rejected": old["rejected"]}
            elif old["state"] == "QUARANTINED":
                # Preserve immutable source identity and rejected-row evidence.
                # A corrected archive must have a different content digest.
                return {"dataset_id": identity, "state": "QUARANTINED", "already_complete": True,
                        "accepted": old["accepted"], "rejected": old["rejected"]}
        with engine.connect() as connection:
            state = connection.execute(select(datasets).where(datasets.c.id == identity)).mappings().one()
            cp_member = state["checkpoint_member"]
            cp_line = state["checkpoint_line"]
            last = state["last_timestamp"]
            already_issues = connection.scalar(select(func.count()).select_from(issues).where(issues.c.dataset_id == identity)) or 0
        batch_candles, batch_issues = [], []
        accepted = rejected = zero = processed = 0
        current_member = cp_member
        current_line = cp_line
        try:
            for member_idx, member in enumerate(members):
                if member_idx < cp_member:
                    continue
                current_member = member_idx
                with archive.open(member) as raw:
                    with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline="") as stream:
                        for line_num, line in enumerate(stream, start=1):
                            if member_idx == cp_member and line_num <= cp_line:
                                continue
                            if len(line) > 1024:
                                record = None
                                reason = "row too long"
                            else:
                                try:
                                    record = decode_row(line.rstrip("\r\n"), file_format, utc_offset_minutes)
                                    if last is not None and record["time"] <= last:
                                        raise ValueError("duplicate or backward timestamp")
                                    reason = None
                                except ValueError as e:
                                    record = None
                                    reason = str(e)[:100]
                            current_line = line_num
                            processed += 1
                            if record is None:
                                rejected += 1
                                if already_issues + len(batch_issues) < quarantine_limit:
                                    batch_issues.append(dict(dataset_id=identity,
                                        member_index=member_idx, line=line_num,
                                        reason=reason, sample=line[:300].rstrip("\r\n")))
                            else:
                                last = record["time"]
                                accepted += 1
                                zero += int(record["volume"] == 0)
                                batch_candles.append(dict(dataset_id=identity, **record,
                                    source_member=member.filename[:255], source_line=line_num))
                            if processed % chunk_rows == 0:
                                _flush(engine, identity, accepted, rejected, zero,
                                       member_idx, line_num, last, batch_candles, batch_issues)
                                already_issues += len(batch_issues)
                                batch_candles.clear(); batch_issues.clear()
                                accepted = rejected = zero = 0
                                if max_rows_per_run is not None and processed >= max_rows_per_run:
                                    return {"dataset_id": identity, "state": "IMPORTING", "paused": True,
                                            "processed_this_run": processed}
                # Each archive.open() stream is fully consumed to verify CRC.
                if batch_candles or batch_issues or accepted or rejected:
                    _flush(engine, identity, accepted, rejected, zero,
                           member_idx, current_line, last, batch_candles, batch_issues)
                    already_issues += len(batch_issues)
                    batch_candles.clear(); batch_issues.clear()
                    accepted = rejected = zero = 0
                # Completing member moves checkpoint to the next member even if empty.
                with engine.begin() as connection:
                    connection.execute(datasets.update().where(datasets.c.id == identity).values(
                        checkpoint_member=member_idx+1, checkpoint_line=0))
                cp_line = 0
            # A ZIP can change after the initial identity hash while its members
            # are being streamed. Never publish READY from changed source bytes.
            # This protects completed/resumed imports; a cooperative pause
            # remains IMPORTING and rechecks the identity when resumed.
            if sha256_file(path) != digest:
                raise ValueError("Archive bytes changed during import; research blocked")
            with engine.begin() as connection:
                totals = connection.execute(select(
                    datasets.c.seen, datasets.c.accepted, datasets.c.rejected
                ).where(datasets.c.id == identity)).mappings().one()
                complete = (totals["rejected"] == 0 and totals["accepted"] > 0
                            and totals["seen"] == totals["accepted"])
                # Never publish a silently truncated/empty series as READY.
                # Retain accepted rows and issue evidence for private review.
                connection.execute(datasets.update().where(datasets.c.id == identity).values(
                    state="READY" if complete else "QUARANTINED",
                    error=None if complete else "Excluded or empty source rows; research blocked"))
        except Exception as exc:
            # Partial data is never presented as READY; checkpoint enables retry.
            with engine.begin() as connection:
                connection.execute(datasets.update().where(datasets.c.id == identity).values(
                    state="FAILED", error=type(exc).__name__ + ": " + str(exc)[:300]))
            raise
    with engine.connect() as connection:
        final = connection.execute(select(datasets).where(datasets.c.id == identity)).mappings().one()
    return {"dataset_id": identity, "state": final["state"],
            "accepted": final["accepted"], "rejected": final["rejected"],
            "zero_volume": final["zero_volume"], "processed_this_run": processed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--format", choices=["ascii", "mt"], default="ascii")
    parser.add_argument("--utc-offset-minutes", type=int, default=-300)
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--init-schema", action="store_true", help="Explicitly create isolated history tables; review production migrations separately")
    parser.add_argument("--chunk-rows", type=int, default=5000)
    args = parser.parse_args(argv)
    # Same engine as the authenticated FastAPI app: this respects private
    # PostgreSQL search_path/statement timeout and never prints credentials.
    from .db import engine
    if args.init_schema:
        create_schema(engine)
    result = ingest(engine, args.archive, instrument=args.instrument, provider=args.provider,
                    file_format=args.format, utc_offset_minutes=args.utc_offset_minutes,
                    rights_confirmed=args.rights_confirmed, chunk_rows=args.chunk_rows)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
