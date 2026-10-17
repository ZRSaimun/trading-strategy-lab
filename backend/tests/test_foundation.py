import os
os.environ['DATABASE_URL']='sqlite://'
os.environ['AUTO_CREATE_SCHEMA']='true'
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app import db
engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
db.engine=engine
db.Session.configure(bind=engine)
from app import main
main.engine=engine
from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from app.market import parse_csv,aggregate
import pytest

CSV='time,open,high,low,close\n2024-01-02T10:00:00Z,2000,2002,1999,2001\n2024-01-02T10:01:00Z,2001,2004,2000,2003\n2024-01-02T11:00:00Z,2003,2006,2002,2005\n'

@pytest.fixture
def client(monkeypatch):
    db.Base.metadata.drop_all(engine);db.Base.metadata.create_all(engine)
    main.attempts.clear()
    monkeypatch.setenv('OWNER_PASSWORD_HASH',PasswordHasher().hash('correct-horse-private-lab'))
    with TestClient(main.app) as c:
        yield c

def unlock(c):
    assert c.post('/api/login',json={'password':'correct-horse-private-lab'}).status_code==200

def test_auth_revocation_and_origin(client):
    assert client.get('/api/instruments').status_code==401
    assert client.post('/api/login',json={'password':'x'},headers={'origin':'https://evil.test'}).status_code==403
    unlock(client)
    assert client.get('/api/instruments').status_code==200
    assert client.post('/api/logout').status_code==200
    assert client.get('/api/instruments').status_code==401

def test_login_rate_limit(client):
    for _ in range(5): assert client.post('/api/login',json={'password':'wrong'}).status_code==401
    assert client.post('/api/login',json={'password':'wrong'}).status_code==429

def test_import_aggregation_quality_and_atomic_failure(client):
    unlock(client)
    assert client.get('/api/candles/XAUUSD-IMPORT').json()['quality']['state']=='NO DATA'
    params={'instrument':'XAUUSD-IMPORT','source':'authorized-test-fixture','rights_confirmed':'true'}
    assert client.post('/api/import',data=params,files={'file':('fixture.csv',CSV)}).status_code==200
    result=client.get('/api/candles/XAUUSD-IMPORT?timeframe=1H').json()
    assert len(result['candles'])==2
    assert result['candles'][0]['open']==2000
    assert result['candles'][0]['close']==2003
    assert result['quality']['state']=='WAIT'
    assert result['quality']['live'] is False
    assert client.post('/api/import',data=params,files={'file':('bad.csv',CSV.replace('2002,1999','1998,1999'))}).status_code==422
    assert client.get('/api/candles/XAUUSD-IMPORT').json()['dataset']['rows']==3
    assert client.get('/api/candles/NQ-IMPORT').status_code==422

def test_drawings_persist_version_and_audit(client):
    unlock(client)
    d={'id':'zone-1','kind':'rectangle','points':[{'time':1704189600,'price':1990},{'time':1704193200,'price':2000}],'text':'Support','version':0}
    assert client.put('/api/drawings/XAUUSD-IMPORT',json=d).json()['version']==1
    assert client.get('/api/drawings/XAUUSD-IMPORT').json()[0]['text']=='Support'
    assert client.put('/api/drawings/XAUUSD-IMPORT',json=d).status_code==409
    assert client.delete('/api/drawings/XAUUSD-IMPORT/zone-1?version=0').status_code==409
    assert client.delete('/api/drawings/XAUUSD-IMPORT/zone-1?version=1').status_code==200
    assert {r['action'] for r in client.get('/api/audit').json()} >= {'drawing.save','drawing.delete'}

def test_strict_csv():
    with pytest.raises(ValueError):parse_csv(CSV.replace('Z',''))
    with pytest.raises(ValueError):parse_csv(CSV+CSV.splitlines()[1]+'\n')
    with pytest.raises(ValueError):parse_csv(CSV.replace('2000,2002','nan,2002'))
    bars=aggregate(parse_csv(CSV),'5m')
    assert [r['observed_minutes'] for r in bars]==[2,1]
    assert bars[0]['time']==1704189600

def test_no_execution_surface(client):
    unlock(client)
    for endpoint in ('/api/orders','/api/trade','/api/broker'):
        assert client.post(endpoint,json={}).status_code==404
