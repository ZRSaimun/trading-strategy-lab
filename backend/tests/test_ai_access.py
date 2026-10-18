import asyncio
import hashlib
import json
import time
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from app import db,main
from app.ai_access import requests as rates
from test_foundation import client,unlock,CSV

def issue(client,scopes=None):
    unlock(client);rates.clear()
    r=client.post('/api/ai/tokens',json={'label':'SDK fixture','scopes':scopes or ['charts:read','drawings:write','notes:write','watchlist:write'],'expires_in_hours':1})
    assert r.status_code==200,r.text
    doc=r.json();return doc,{'authorization':'Bearer '+doc['token']}
def call(client,name,arguments,headers):return client.post('/api/ai/tools/'+name,json=arguments,headers=headers)
def drawing(**extra):return {'instrument':'XAUUSD-IMPORT','id':'ai-fixture','kind':'rectangle','points':[{'time':1704189600,'price':1990},{'time':1704193200,'price':2000}],'text':'AI fixture, not current market analysis','version':0,'idempotency_key':'create-fixture',**extra}

def test_tokens_require_owner_and_store_only_hashes(client):
    assert client.post('/api/ai/tokens',json={'label':'x','scopes':['charts:read']}).status_code==401
    doc,headers=issue(client)
    with db.Session() as session:
        rows=session.query(db.Record).all();assert all(doc['token'] not in r.value and doc['token'] not in r.key for r in rows)
    assert doc['token'] not in client.get('/api/ai/tokens').text
    assert doc['token'] not in client.get('/api/audit').text
    assert client.post('/api/ai/tokens',json={'label':'x','scopes':['shell:execute']}).status_code==422
    assert client.post('/api/ai/tokens',json={'label':'x','scopes':['charts:read'],'expires_in_hours':721}).status_code==422
    assert call(client,'list_instruments',{},{}).status_code==401
    assert call(client,'list_instruments',{},headers).status_code==200

def test_scope_denial_expiry_revocation_and_request_throttle(client):
    doc,headers=issue(client,['charts:read'])
    assert call(client,'create_chart_drawing',drawing(),headers).status_code==403
    rates[doc['id']].extend([time.monotonic()]*120)
    assert call(client,'list_instruments',{},headers).status_code==429
    rates.clear()
    assert client.delete('/api/ai/tokens/'+doc['id']).status_code==200
    assert call(client,'list_instruments',{},headers).status_code==401
    expired,eh=issue(client,['charts:read'])
    with db.Session() as session:
        rec=session.get(db.Record,'ai-token:'+hashlib.sha256(expired['token'].encode()).hexdigest());value=json.loads(rec.value);value['expires_at']=0;rec.value=json.dumps(value);session.commit()
    assert call(client,'list_instruments',{},eh).status_code==401

def test_ai_drawings_are_idempotent_versioned_audited_and_editable_by_owner(client):
    doc,headers=issue(client)
    a=call(client,'create_chart_drawing',drawing(),headers);assert a.status_code==200,a.text
    assert a.json()['provenance']=='ai' and a.json()['version']==1
    assert call(client,'create_chart_drawing',drawing(),headers).json()==a.json()
    assert call(client,'create_chart_drawing',drawing(text='changed content'),headers).status_code==409
    assert call(client,'update_chart_drawing',drawing(version=0,idempotency_key='bad-version'),headers).status_code==409
    update=call(client,'update_chart_drawing',drawing(version=1,text='Edited AI fixture',idempotency_key='update-fixture'),headers)
    assert update.status_code==200 and update.json()['version']==2
    manual={k:v for k,v in drawing(version=2,text='Owner correction').items() if k not in ('instrument','idempotency_key')}
    edited=client.put('/api/drawings/XAUUSD-IMPORT',json=manual);assert edited.status_code==200 and edited.json()['provenance']=='ai'
    logs=client.get('/api/audit').json();assert sum(r['action']=='ai.create_chart_drawing' for r in logs)==1
    assert any(r['actor']=='ai:'+doc['id'] and r['action']=='ai.update_chart_drawing' for r in logs)
    delete={'instrument':'XAUUSD-IMPORT','id':'ai-fixture','version':3,'idempotency_key':'delete-fixture'}
    assert call(client,'delete_chart_drawing',delete,headers).status_code==200
    assert call(client,'delete_chart_drawing',delete,headers).status_code==200
    assert client.get('/api/drawings/XAUUSD-IMPORT').json()==[]

def test_ai_strict_schema_quality_identity_notes_watchlist_and_no_execution(client):
    _,headers=issue(client)
    assert call(client,'get_candles',{'instrument':'NQ-IMPORT'},headers).status_code==422
    assert call(client,'get_candles',{'instrument':'XAUUSD-IMPORT','limit':2001},headers).status_code==422
    assert call(client,'get_candles',{'instrument':'XAUUSD-IMPORT','limit':'500'},headers).status_code==422
    assert call(client,'create_chart_drawing',drawing(points=[{'time':10**20,'price':1},{'time':1704193200,'price':2}]),headers).status_code==422
    assert call(client,'get_candles',{'instrument':'XAUUSD-IMPORT','code':'print(1)'},headers).status_code==422
    assert call(client,'get_candles',{'instrument':'XAUUSD-IMPORT'},headers).json()['quality']['state']=='NO DATA'
    client.post('/api/import',data={'instrument':'XAUUSD-IMPORT','source':'software-only fixture','rights_confirmed':'true'},files={'file':('fixture.csv',CSV)})
    result=call(client,'get_candles',{'instrument':'XAUUSD-IMPORT','timeframe':'1H','limit':1},headers).json()
    assert len(result['candles'])==1 and result['has_more'] and result['quality']['state']=='WAIT' and result['quality']['live'] is False
    note=call(client,'save_analysis_note',{'instrument':'XAUUSD-IMPORT','text':'WAIT — software fixture only','idempotency_key':'note-fixture'},headers)
    assert note.status_code==200 and note.json()['provenance']=='ai'
    assert client.get('/api/ai/notes').json()[0]['text'].startswith('WAIT')
    watch={'instruments':['NDX-IMPORT'],'version':0,'idempotency_key':'watch-fixture'}
    assert call(client,'update_watchlist',watch,headers).json()['version']==1
    client.put('/api/watchlist',json={'instruments':['XAUUSD-IMPORT']})
    assert call(client,'update_watchlist',{**watch,'version':1,'idempotency_key':'stale-watch'},headers).status_code==409
    for name in ['place_order','execute_code','get_provider_secret']:
        assert call(client,name,{},headers).status_code==404

def test_official_sdk_http_read_draw_audit_revoke_denied(client):
    doc,headers=issue(client)
    assert client.post('/api/mcp/',json={}).status_code==401
    async def exercise():
        statuses=[]
        async def capture(response):statuses.append(response.status_code)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=main.app),headers=headers,base_url='http://localhost',event_hooks={'response':[capture]}) as http:
            async with Client(streamable_http_client('http://localhost/api/mcp/',http_client=http),cache=None) as sdk:
                tools=await sdk.list_tools();names={t.name for t in tools.tools};assert 'create_chart_drawing' in names and 'get_candles' in names
                result=await sdk.call_tool('get_candles',{'request':{'instrument':'XAUUSD-IMPORT'}});assert not result.is_error
                created=await sdk.call_tool('create_chart_drawing',{'request':drawing(id='sdk-drawing',idempotency_key='sdk-create')});assert not created.is_error,created
                rows=client.get('/api/drawings/XAUUSD-IMPORT').json();assert rows[0]['provenance']=='ai'
                assert any(r['action']=='ai.create_chart_drawing' for r in client.get('/api/audit').json())
                assert client.delete('/api/ai/tokens/'+doc['id']).status_code==200
                # Use the same SDK connection; the next HTTP request must check revocation again.
                try:
                    denied=await sdk.call_tool('list_instruments',{})
                    assert denied.is_error
                except Exception:
                    assert statuses[-1]==401
                assert call(client,'create_chart_drawing',drawing(id='denied-drawing',idempotency_key='revoked-write'),headers).status_code==401
                assert len(client.get('/api/drawings/XAUUSD-IMPORT').json())==1
    asyncio.run(exercise())

def test_ai_streaming_size_and_mcp_origin_host_checks(client):
    _,headers=issue(client)
    assert client.post('/api/ai/tools/list_instruments',content=(b'x'*1000001),headers={**headers,'Content-Type':'application/json'}).status_code==413
    message={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'fixture','version':'1'}}}
    valid={**headers,'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
    assert client.post('/api/mcp/',json=message,headers={**valid,'Host':'evil.test'}).status_code==421
    assert client.post('/api/mcp/',json=message,headers={**valid,'Origin':'https://evil.test'}).status_code==403
