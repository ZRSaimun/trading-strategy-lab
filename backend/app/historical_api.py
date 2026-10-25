"""Read-only chart access to completed source-isolated historical datasets."""
from types import SimpleNamespace
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from .bulk_import import datasets, candles
from .history import latest_aggregates
from .market import TIMEFRAMES, bucket


def attach_history(owner, engine):
    router = APIRouter()

    @router.get('/api/history/datasets')
    def ready_datasets(response: Response,
                       offset: int = Query(default=0, ge=0, le=1_000_000),
                       limit: int = Query(default=200, ge=1, le=200),
                       snapshot: str | None = Query(default=None, pattern=r'^[a-f0-9]{64}$'),
                       auth=Depends(owner)):
        # One ordered SQL statement supplies both the page and a fingerprint
        # of ALL READY source identities. An optional client snapshot rejects
        # shifted offset pages after another archive becomes READY.
        #
        # A single statement sees a consistent set in PostgreSQL/SQLite; no
        # database locks, schema changes, price reads, or long-lived sessions.
        fields = (
            datasets.c.id, datasets.c.provider, datasets.c.instrument,
            datasets.c.format, datasets.c.utc_offset_minutes,
            datasets.c.archive_sha256, datasets.c.state,
            datasets.c.accepted, datasets.c.rejected, datasets.c.zero_volume,
        )
        fingerprint = hashlib.sha256()
        page = []
        count = 0
        with engine.connect() as connection:
            stream = connection.execution_options(stream_results=True).execute(
                select(*fields).where(
                    datasets.c.state == 'READY', datasets.c.rejected == 0,
                    datasets.c.accepted > 0, datasets.c.seen == datasets.c.accepted
                ).order_by(
                    datasets.c.instrument, datasets.c.provider, datasets.c.id
                )
            ).mappings()
            for row in stream:
                # Explicit field order and JSON delimiters make the digest
                # unambiguous and deterministic across database drivers.
                fingerprint.update(json.dumps(
                    [row[column.key] for column in fields],
                    separators=(',', ':'), ensure_ascii=True,
                ).encode('utf-8'))
                fingerprint.update(b'\n')
                if offset <= count < offset + limit:
                    page.append(dict(row))
                count += 1

        current_snapshot = fingerprint.hexdigest()
        if snapshot is not None and snapshot != current_snapshot:
            raise HTTPException(
                409, 'READY archive inventory changed; restart listing from offset 0'
            )
        response.headers['X-History-Snapshot'] = current_snapshot
        has_more = count > offset + limit
        response.headers['X-History-Has-More'] = 'true' if has_more else 'false'
        if has_more:
            response.headers['X-History-Next-Offset'] = str(offset + limit)
        return page

    @router.get('/api/history/{dataset_id}/candles')
    def historical_candles(dataset_id: str, timeframe: str = '5m',
                           before: int | None = Query(default=None, ge=0, le=253402300740),
                           limit: int = Query(default=2000, ge=1, le=2000),
                           auth=Depends(owner)):
        if not re.fullmatch(r'[a-f0-9]{64}', dataset_id):
            raise HTTPException(422, 'Invalid dataset ID')
        if timeframe not in TIMEFRAMES:
            raise HTTPException(422, 'Unsupported timeframe')
        # Bound the cursor to the UTC datetime range supported by bucket().
        # Without this, huge integer cursors trigger OverflowError/ValueError
        # (HTTP 500) before we reach the database, particularly on 1M pages.
        if before is not None and before != bucket(before, timeframe):
            raise HTTPException(422, 'before must be a complete timeframe bucket boundary')
        with engine.connect() as connection:
            item = connection.execute(select(datasets).where(
                datasets.c.id == dataset_id, datasets.c.state == 'READY',
                datasets.c.rejected == 0, datasets.c.accepted > 0,
                datasets.c.seen == datasets.c.accepted)).mappings().first()
            if item is None:
                raise HTTPException(404, 'Completed dataset not found')
            stmt = select(candles).where(candles.c.dataset_id == dataset_id)
            if before is not None:
                stmt = stmt.where(candles.c.time < before)
            stream = connection.execution_options(stream_results=True).execute(
                stmt.order_by(candles.c.time.desc())).mappings()
            bars, has_more = latest_aggregates(
                (SimpleNamespace(**record) for record in stream), timeframe, limit=limit)
        return {'dataset': {'id': item['id'], 'provider': item['provider'],
                            'instrument': item['instrument'], 'state': item['state'],
                            'archive_sha256': item['archive_sha256'],
                            'format': item['format'],
                            'utc_offset_minutes': item['utc_offset_minutes'],
                            'accepted': item['accepted'], 'rejected': item['rejected'],
                            'zero_volume': item['zero_volume']},
                'candles': bars, 'has_more': has_more,
                'next_before': bars[0]['time'] if has_more and bars else None,
                'quality': {'live': False, 'price_side': 'bid',
                            'volume_type': 'unverified_histdata',
                            'state': 'HISTORICAL ONLY',
                            'message': 'Observed bid OHLC; no verified ask/spread data or execution quotes.'}}

    return router
