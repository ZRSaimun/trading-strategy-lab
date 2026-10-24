"""Authenticated API regression tests for imported historical datasets."""
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.bulk_import import create_schema, ingest, datasets
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
    snapshot = first.headers['x-history-snapshot']
    assert len(snapshot) == 64
    second = client.get('/api/history/datasets', params={
        'limit': 1, 'offset': 1, 'snapshot': snapshot})
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


def test_inventory_snapshot_rejects_changed_ready_set_and_metadata(tmp_path):
    """A new READY archive must never silently shift an offset-paged inventory."""
    p = tmp_path / 'same-source.zip'
    with ZipFile(p, 'w') as archive:
        archive.writestr('DAT_ASCII_XAUUSD_M1_202610.csv',
                         '20261001 090000;1;2;0.5;1.5;0\n')
    e = create_engine('sqlite:///' + str(tmp_path / 'snapshot.db'))
    create_schema(e)
    first_import = ingest(e, p, instrument='XAUUSD-CFD', provider='HistData',
                          utc_offset_minutes=-300, rights_confirmed=True)
    ingest(e, p, instrument='XAUUSD-CFD', provider='HistData',
           utc_offset_minutes=0, rights_confirmed=True)
    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)

    first = client.get('/api/history/datasets', params={'limit': 1})
    assert first.status_code == 200
    original = first.headers['x-history-snapshot']
    assert client.get('/api/history/datasets', params={
        'limit': 1, 'offset': 1, 'snapshot': original}).status_code == 200
    assert client.get('/api/history/datasets', params={
        'limit': 200}).headers['x-history-snapshot'] == original

    # Third archive is a separate source identity because its declared
    # fixed offset differs, even though its ZIP bytes are identical.
    ingest(e, p, instrument='XAUUSD-CFD', provider='HistData',
           utc_offset_minutes=60, rights_confirmed=True)
    stale = client.get('/api/history/datasets', params={
        'limit': 1, 'offset': 1, 'snapshot': original})
    assert stale.status_code == 409
    assert 'restart' in stale.json()['detail'].lower()
    fresh = client.get('/api/history/datasets', params={'limit': 1})
    assert fresh.status_code == 200
    assert fresh.headers['x-history-snapshot'] != original
    assert client.get('/api/history/datasets', params={
        'limit': 1, 'offset': 1,
        'snapshot': fresh.headers['x-history-snapshot']}).status_code == 200

    # Even if an importer/administrator unexpectedly rewrites READY
    # provenance counters, the fingerprint detects that inconsistency.
    with e.begin() as connection:
        connection.execute(datasets.update().where(
            datasets.c.id == first_import['dataset_id']).values(rejected=7))
    assert client.get('/api/history/datasets', params={
        'limit': 1, 'offset': 1,
        'snapshot': fresh.headers['x-history-snapshot']}).status_code == 409
    assert client.get('/api/history/datasets', params={
        'snapshot': 'bad'}).status_code == 422


def test_empty_ready_inventory_has_stable_snapshot(tmp_path):
    e = create_engine('sqlite:///' + str(tmp_path / 'empty.db'))
    create_schema(e)
    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)
    first = client.get('/api/history/datasets')
    assert first.status_code == 200 and first.json() == []
    assert first.headers['x-history-has-more'] == 'false'
    assert len(first.headers['x-history-snapshot']) == 64
    repeat = client.get('/api/history/datasets', params={
        'snapshot': first.headers['x-history-snapshot']})
    assert repeat.status_code == 200 and repeat.json() == []


def test_inventory_paging_over_200_and_ready_transition(tmp_path):
    """Full two-page discovery must detect a concurrent READY transition.

    Synthetic metadata only: no ZIP download, provider access, or prices.
    """
    e = create_engine('sqlite:///' + str(tmp_path / 'many-archives.db'))
    create_schema(e)
    rows = [
        dict(id=f'{i:064x}', provider='HistData', instrument='XAUUSD-OTC',
             format='ascii', utc_offset_minutes=-300,
             archive_sha256=f'{i + 1000:064x}', archive_filename=f'{i}.zip',
             state='READY' if i < 202 else 'IMPORTING',
             seen=100, accepted=100, rejected=0, zero_volume=100,
             checkpoint_member=1, checkpoint_line=0)
        for i in range(203)
    ]
    with e.begin() as connection:
        connection.execute(datasets.insert(), rows)

    app = FastAPI()
    app.include_router(attach_history(lambda: 'owner', e))
    client = TestClient(app)

    first = client.get('/api/history/datasets')
    assert first.status_code == 200
    assert len(first.json()) == 200
    assert first.headers['x-history-has-more'] == 'true'
    assert first.headers['x-history-next-offset'] == '200'
    original = first.headers['x-history-snapshot']

    last = client.get('/api/history/datasets', params={
        'offset': 200, 'snapshot': original})
    assert last.status_code == 200
    assert len(last.json()) == 2
    assert last.headers['x-history-has-more'] == 'false'
    assert last.headers['x-history-snapshot'] == original
    combined = first.json() + last.json()
    assert [r['id'] for r in combined] == [f'{i:064x}' for i in range(202)]
    assert all(r['state'] == 'READY' for r in combined)

    # A previously unfinished import becoming READY changes the inventory.
    with e.begin() as connection:
        connection.execute(datasets.update().where(
            datasets.c.id == f'{202:064x}').values(state='READY'))
    assert client.get('/api/history/datasets', params={
        'offset': 200, 'snapshot': original}).status_code == 409

    fresh = client.get('/api/history/datasets')
    assert fresh.status_code == 200
    assert fresh.headers['x-history-snapshot'] != original
    final = client.get('/api/history/datasets', params={
        'offset': 200, 'snapshot': fresh.headers['x-history-snapshot']})
    assert final.status_code == 200
    assert len(final.json()) == 3
    assert final.json()[-1]['id'] == f'{202:064x}'
    assert final.headers['x-history-has-more'] == 'false'
