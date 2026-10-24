"""Read-only chart access to completed source-isolated historical datasets."""
from types import SimpleNamespace
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
                       auth=Depends(owner)):
        # Preserve the existing JSON array contract, but allow callers to
        # retrieve READY archives beyond the first 200 without silent loss.
        with engine.connect() as connection:
            rows = connection.execute(select(
                datasets.c.id, datasets.c.provider, datasets.c.instrument,
                datasets.c.format, datasets.c.utc_offset_minutes,
                datasets.c.archive_sha256, datasets.c.state,
                datasets.c.accepted, datasets.c.rejected, datasets.c.zero_volume
            ).where(datasets.c.state == 'READY').order_by(
                datasets.c.instrument, datasets.c.provider, datasets.c.id
            ).offset(offset).limit(limit + 1)).mappings().all()
        has_more = len(rows) > limit
        response.headers['X-History-Has-More'] = 'true' if has_more else 'false'
        if has_more:
            response.headers['X-History-Next-Offset'] = str(offset + limit)
        return [dict(row) for row in rows[:limit]]

    @router.get('/api/history/{dataset_id}/candles')
    def historical_candles(dataset_id: str, timeframe: str = '5m',
                           before: int | None = None,
                           limit: int = Query(default=2000, ge=1, le=2000),
                           auth=Depends(owner)):
        if not re.fullmatch(r'[a-f0-9]{64}', dataset_id):
            raise HTTPException(422, 'Invalid dataset ID')
        if timeframe not in TIMEFRAMES:
            raise HTTPException(422, 'Unsupported timeframe')
        if before is not None and (before < 0 or before != bucket(before, timeframe)):
            raise HTTPException(422, 'before must be a complete timeframe bucket boundary')
        with engine.connect() as connection:
            item = connection.execute(select(datasets).where(
                datasets.c.id == dataset_id, datasets.c.state == 'READY')).mappings().first()
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
