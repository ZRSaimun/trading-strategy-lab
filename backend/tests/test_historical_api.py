"""Authenticated API regression tests for imported historical datasets."""
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.bulk_import import create_schema, ingest
from app.historical_api import attach_history


def test_chart_endpoint_uses_completed_provider_dataset_and_paging(tmp_path):
    p = tmp_path / 'a.zip'
    with ZipFile(p, 'w') as archive:
        archive.writestr('DAT_ASCII_XAUUSD_M1_202610.csv', ''.join(
            f'20261001 {hour:02d}{minute:02d}00;1;2;0.5;1.5;0\n'
            for hour in range(8, 12) for minute in range(60)))
    e = create_engine('sqlite:///' + str(tmp_path / 'research.db'))
    create_schema(e)
    result = ingest(e, p, instrument='XAUUSD-CFD', provider='HistData', rights_confirmed=True)
    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)
    ds = client.get('/api/history/datasets')
    assert ds.status_code == 200 and len(ds.json()) == 1
    identifier = result['dataset_id']
    resp = client.get(f'/api/history/{identifier}/candles', params={'timeframe': '1H', 'limit': 2})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()['candles']) == 2 and resp.json()['has_more']
    older = client.get(f'/api/history/{identifier}/candles', params={
        'timeframe': '1H', 'limit': 2, 'before': resp.json()['next_before']})
    assert older.status_code == 200 and len(older.json()['candles']) == 2
    assert not older.json()['has_more']
    bad = client.get(f'/api/history/{identifier}/candles', params={
        'timeframe': '1H', 'before': resp.json()['next_before'] + 60})
    assert bad.status_code == 422


def test_endpoint_rejects_partial_or_missing_dataset(tmp_path):
    e = create_engine('sqlite:///' + str(tmp_path / 'research.db'))
    create_schema(e)
    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)
    assert client.get('/api/history/' + 'a'*64 + '/candles').status_code == 404
    assert client.get('/api/history/foobar/candles').status_code == 422
