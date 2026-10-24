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
    assert ds.headers['x-history-has-more'] == 'false'
    assert ds.json()[0]['format'] == 'ascii'
    assert ds.json()[0]['utc_offset_minutes'] == -300
    assert ds.json()[0]['archive_sha256'] and len(ds.json()[0]['archive_sha256']) == 64
    identifier = result['dataset_id']
    resp = client.get(f'/api/history/{identifier}/candles', params={'timeframe': '1H', 'limit': 2})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()['candles']) == 2 and resp.json()['has_more']
    assert resp.json()['dataset']['utc_offset_minutes'] == -300
    assert resp.json()['dataset']['format'] == 'ascii'
    assert resp.json()['dataset']['accepted'] == 240
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


def test_dataset_list_pagination_and_offset_identity(tmp_path):
    """Same ZIP at different declared clocks is never silently relabelled."""
    p = tmp_path / 'clock.zip'
    with ZipFile(p, 'w') as archive:
        archive.writestr('DAT_ASCII_XAUUSD_M1_202610.csv',
                         '20261001 090000;1;2;0.5;1.5;0\n')
    e = create_engine('sqlite:///' + str(tmp_path / 'clock.db'))
    create_schema(e)
    for offset in (-300, 0):
        ingest(e, p, instrument='XAUUSD-CFD', provider='HistData',
               utc_offset_minutes=offset, rights_confirmed=True)
    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)
    first = client.get('/api/history/datasets', params={'limit': 1})
    assert first.status_code == 200
    assert first.headers['x-history-has-more'] == 'true'
    assert first.headers['x-history-next-offset'] == '1'
    second = client.get('/api/history/datasets', params={'limit': 1, 'offset': 1})
    assert second.status_code == 200
    assert second.headers['x-history-has-more'] == 'false'
    assert 'x-history-next-offset' not in second.headers
    entries = first.json() + second.json()
    assert len({item['id'] for item in entries}) == 2
    assert {item['utc_offset_minutes'] for item in entries} == {-300, 0}
    assert len({item['archive_sha256'] for item in entries}) == 1
    assert all(item['format'] == 'ascii' and item['accepted'] == 1 for item in entries)
    observed_times = []
    for item in entries:
        response = client.get(f"/api/history/{item['id']}/candles", params={'timeframe': '1m'})
        assert response.status_code == 200
        assert response.json()['dataset']['utc_offset_minutes'] == item['utc_offset_minutes']
        assert response.json()['dataset']['archive_sha256'] == item['archive_sha256']
        observed_times.append(response.json()['candles'][0]['time'])
    assert abs(observed_times[0] - observed_times[1]) == 5 * 3600
    assert client.get('/api/history/datasets', params={'limit': 201}).status_code == 422
    assert client.get('/api/history/datasets', params={'offset': -1}).status_code == 422
    assert client.get('/api/history/datasets', params={'offset': 2}).json() == []
