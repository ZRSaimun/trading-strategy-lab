"""Source-isolated native Gold CSV inspection; never routes H1 bars into M1 engines."""
import csv
import hashlib
import io
import json
import math
import re
import time
from datetime import datetime, timezone

NAME = re.compile(r'XAU-USD_(1Hour|1Min)_(BID|ASK)_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_Etc_UTC\.csv')
PREFIX = 'gold-csv:'


def inspect_gold_csv(raw, filename, now=None):
    match = NAME.fullmatch(filename or '')
    if not match:
        raise ValueError('Use an original XAU-USD 1Hour or 1Min BID/ASK export in Etc/UTC; do not rename other instruments.')
    interval, side, start, end = match.groups()
    seconds = 3600 if interval == '1Hour' else 60
    start_date = datetime.strptime(start, '%Y-%m-%d').date()
    end_date = datetime.strptime(end, '%Y-%m-%d').date()
    if end_date < start_date:
        raise ValueError('Filename date range is reversed')
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')))
    if next(reader, None) != ['Etc/UTC', 'Open', 'High', 'Low', 'Close', 'Volume']:
        raise ValueError('Expected original Etc/UTC,Open,High,Low,Close,Volume headers')
    bars = []
    current = time.time() if now is None else now
    for line, row in enumerate(reader, 2):
        if len(bars) >= 5000:
            raise ValueError('Maximum 5,000 bars; export a smaller date window')
        try:
            if len(row) != 6:
                raise ValueError('Expected six columns')
            dt = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
            if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
                raise ValueError('Explicit UTC timestamp required')
            t = int(dt.timestamp())
            if dt.microsecond or t % seconds:
                raise ValueError('Timestamp does not match declared interval')
            if not start_date <= dt.date() <= end_date:
                raise ValueError('Timestamp outside filename date range')
            if t + seconds > current:
                raise ValueError('Future or incomplete candle')
            if bars and t <= bars[-1]['time']:
                raise ValueError('Duplicate or out-of-order timestamp')
            o, h, l, c, v = map(float, row[1:])
            if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o,h,l,c) <= 0 or v < 0 or l > min(o,c) or h < max(o,c) or l > h:
                raise ValueError('Invalid OHLC or volume')
            bars.append(dict(time=t, open=o, high=h, low=l, close=c, volume=v))
        except (ValueError, OverflowError) as exc:
            raise ValueError(f'Row {line}: {exc}') from exc
    if not bars:
        raise ValueError('CSV contains no prices; choose a completed trading date range')
    spans = [dict(start=a['time'], end=b['time'], unobserved_intervals=(b['time']-a['time'])//seconds-1)
             for a,b in zip(bars,bars[1:]) if b['time']-a['time'] > seconds]
    return dict(id=hashlib.sha256(filename.encode()+b'\0'+raw).hexdigest(), filename=filename,
                sha256=hashlib.sha256(raw).hexdigest(), instrument='XAU/USD',
                provider='User-supplied Dukascopy-format export (unverified)',
                interval_seconds=seconds, price_side=side, timezone='UTC',
                volume_type='unknown', live=False, rows=len(bars), start=bars[0]['time'],
                end=bars[-1]['time'], unobserved_spans=spans, candles=bars)


def build_router(owner, session_factory=None):
    from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from .db import Session, Record, Audit
    sessions = session_factory or Session
    router = APIRouter(prefix='/api/gold-csv', dependencies=[Depends(owner)])

    @router.post('')
    async def upload(file: UploadFile = File(...), rights_confirmed: bool = Form(...)):
        if not rights_confirmed:
            raise HTTPException(422, 'Confirm authorization to use this dataset')
        raw = await file.read(1_000_001)
        if len(raw) > 1_000_000:
            raise HTTPException(413, 'Maximum 1 MB per Gold CSV')
        try:
            doc = inspect_gold_csv(raw, file.filename)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        with sessions() as db:
            key = PREFIX+doc['id']
            if not db.get(Record, key):
                doc['imported_at'] = int(time.time())
                db.add(Record(key=key, value=json.dumps(doc)))
                db.add(Audit(time=int(time.time()), actor='owner', action='gold_csv.import', detail=json.dumps({k:doc[k] for k in ('id','sha256','rows','interval_seconds','price_side')})))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    if not db.get(Record, key):
                        raise
            return json.loads(db.get(Record, key).value)

    @router.get('')
    def listing():
        with sessions() as db:
            docs = [json.loads(r.value) for r in db.scalars(select(Record).where(Record.key.startswith(PREFIX))).all()]
        return [{k:v for k,v in d.items() if k not in ('candles','unobserved_spans')} for d in docs]

    @router.get('/{dataset_id}')
    def dataset(dataset_id: str):
        if not re.fullmatch('[0-9a-f]{64}', dataset_id):
            raise HTTPException(422, 'Invalid dataset id')
        with sessions() as db:
            r = db.get(Record, PREFIX+dataset_id)
            if not r:
                raise HTTPException(404, 'Dataset not found')
            return json.loads(r.value)

    return router
