from datetime import datetime, timezone
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base, Audit, Candle
from app.gold_csv_research import inspect_gold_csv, build_router
NAME='XAU-USD_1Hour_BID_2026-09-01_to_2026-10-01_Etc_UTC.csv'
HEADER='Etc/UTC,Open,High,Low,Close,Volume\n'
ROWS='2026-09-01T00:00:00+00:00,100,102,99,101,1000\n2026-09-01T02:00:00+00:00,101,103,100,102,500\n'
NOW=datetime(2026,10,25,tzinfo=timezone.utc).timestamp()
def test_native_hour():
 d=inspect_gold_csv((HEADER+ROWS).encode(),NAME,NOW)
 assert d['rows']==2 and d['interval_seconds']==3600 and not d['live']
 assert d['volume_type']=='unknown' and d['price_side']=='BID'
 assert d['unobserved_spans'][0]['unobserved_intervals']==1
 assert inspect_gold_csv((HEADER+ROWS).encode(),NAME.replace('BID','ASK'),NOW)['id']!=d['id']
@pytest.mark.parametrize('rows',['',ROWS+ROWS,ROWS.replace('00:00:00+00:00','00:30:00+00:00'),ROWS.replace(',102,99,',',98,99,'),ROWS.replace(',1000',',nan'),ROWS.replace('+00:00',''),ROWS.replace('+00:00','+01:00'),ROWS.replace('2026-09-01','2026-08-31')])
def test_invalid(rows):
 with pytest.raises(ValueError):inspect_gold_csv((HEADER+rows).encode(),NAME,NOW)
def test_incomplete_and_wrong_instrument():
 with pytest.raises(ValueError,match='incomplete'):inspect_gold_csv((HEADER+ROWS).encode(),NAME,datetime(2026,9,1,2,30,tzinfo=timezone.utc).timestamp())
 for name in [NAME.replace('XAU','EUR'),NAME.replace('1Hour','5Min')]:
  with pytest.raises(ValueError):inspect_gold_csv((HEADER+ROWS).encode(),name,NOW)
def test_api(tmp_path,monkeypatch):
 monkeypatch.setattr('app.gold_csv_research.time.time',lambda:NOW)
 engine=create_engine('sqlite:///'+str(tmp_path/'db.sqlite'),connect_args={'check_same_thread':False})
 Base.metadata.create_all(engine);sessions=sessionmaker(engine);authorized=True
 def owner():
  if not authorized:raise HTTPException(401,'Login required')
 app=FastAPI();app.include_router(build_router(owner,sessions));client=TestClient(app)
 def upload(content=HEADER+ROWS,rights='true'):
  return client.post('/api/gold-csv',files={'file':(NAME,content,'text/csv')},data={'rights_confirmed':rights})
 authorized=False
 assert client.get('/api/gold-csv').status_code==401 and upload().status_code==401
 authorized=True
 assert upload(rights='false').status_code==422 and upload(HEADER).status_code==422
 saved=upload();assert saved.status_code==200
 identifier=saved.json()['id'];assert upload().json()['id']==identifier
 assert len(client.get('/api/gold-csv').json())==1
 assert 'candles' not in client.get('/api/gold-csv').json()[0]
 assert len(client.get('/api/gold-csv/'+identifier).json()['candles'])==2
 assert upload(HEADER+ROWS+ROWS).status_code==422
 with sessions() as db:
  assert db.scalar(select(func.count()).select_from(Audit))==1
  assert db.scalar(select(func.count()).select_from(Candle))==0
 assert client.get('/api/gold-csv/not-an-id').status_code==422
 assert client.get('/api/gold-csv/'+'f'*64).status_code==404
 assert upload('x'*1_000_001).status_code==413
