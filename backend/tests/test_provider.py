import asyncio
import json
from pathlib import Path
import httpx
import pytest
from cryptography.fernet import Fernet
from app.providers.vault import load_key,CredentialUnavailable
from app.providers.twelvedata import normalize,retrieve,ProviderError
from app import provider_api
from test_foundation import client,unlock

KEY='testsecret1234567890'
NOW=1700001000
PAYLOAD={'status':'ok','meta':{'symbol':'XAU/USD','interval':'1min','exchange_timezone':'UTC'},'values':[
 {'datetime':'2023-11-14 22:15:00','open':'2001','high':'2003','low':'2000','close':'2002'},
 {'datetime':'2023-11-14 22:14:00','open':'2000','high':'2002','low':'1999','close':'2001'}]}

def credentials(monkeypatch,tmp_path):
    master=Fernet.generate_key();(tmp_path/'master').write_bytes(master);(tmp_path/'key').write_bytes(Fernet(master).encrypt(KEY.encode()))
    monkeypatch.setenv('PROVIDER_MASTER_KEY_FILE',str(tmp_path/'master'))
    monkeypatch.setenv('TWELVEDATA_KEY_FILE',str(tmp_path/'key'))


def test_vault_encryption_and_wrong_key_denied(monkeypatch,tmp_path):
    credentials(monkeypatch,tmp_path);assert load_key()==KEY
    assert KEY.encode() not in (tmp_path/'key').read_bytes()
    (tmp_path/'master').write_bytes(Fernet.generate_key())
    with pytest.raises(CredentialUnavailable):load_key()


def test_exact_metadata_duplicates_and_completed_candles():
    rows,archive=normalize(PAYLOAD,'XAUUSD-TD',NOW)
    assert len(rows)==2;assert rows[0]['time']<rows[1]['time'];assert rows[0]['close']==2001
    assert b'XAU/USD' in archive
    wrong={**PAYLOAD,'meta':{**PAYLOAD['meta'],'symbol':'XAG/USD'}}
    with pytest.raises(ProviderError):normalize(wrong,'XAUUSD-TD',NOW)
    duplicate={**PAYLOAD,'values':[PAYLOAD['values'][0],PAYLOAD['values'][0]]}
    with pytest.raises(ProviderError):normalize(duplicate,'XAUUSD-TD',NOW)
    partial={**PAYLOAD,'values':[PAYLOAD['values'][0],{'datetime':'2030-01-01 00:00:00','open':'1','high':'1','low':'1','close':'1'}]}
    assert len(normalize(partial,'XAUUSD-TD',NOW)[0])==1


def test_transport_pins_host_and_keeps_key_out_of_query():
    seen=[]
    def handler(request):
        seen.append(request)
        assert request.url.host=='api.twelvedata.com';assert 'apikey' not in request.url.params
        assert request.headers['Authorization']=='apikey '+KEY
        assert request.url.params['symbol']=='XAU/USD';assert request.url.params['timezone']=='UTC'
        return httpx.Response(200,json=PAYLOAD)
    rows,_=asyncio.run(retrieve(KEY,'XAUUSD-TD',100,NOW-60,NOW,httpx.MockTransport(handler)))
    assert len(rows)==2;assert len(seen)==1


def test_quota_and_error_messages_do_not_echo_secrets():
    def handler(request):return httpx.Response(429,json={'message':'key='+KEY})
    with pytest.raises(ProviderError) as err:asyncio.run(retrieve(KEY,'XAUUSD-TD',100,NOW-60,NOW,httpx.MockTransport(handler)))
    assert err.value.status==429;assert KEY not in str(err.value)
    with pytest.raises(ProviderError):normalize({'status':'error','code':403,'message':KEY},'XAUUSD-TD',NOW)


def test_redirect_and_out_of_bounds_response_rejected():
    def redirect(request):return httpx.Response(302,headers={'Location':'https://evil.example/?key='+KEY})
    with pytest.raises(ProviderError):asyncio.run(retrieve(KEY,'XAUUSD-TD',10,NOW-60,NOW,httpx.MockTransport(redirect)))
    def ok(request):return httpx.Response(200,json=PAYLOAD)
    with pytest.raises(ProviderError):asyncio.run(retrieve(KEY,'XAUUSD-TD',1,NOW-60,NOW,httpx.MockTransport(ok)))


def test_status_authentication_disabled_gate_and_secret_isolation(client,monkeypatch,tmp_path):
    credentials(monkeypatch,tmp_path);monkeypatch.setenv('TWELVEDATA_ENABLED','false')
    assert client.get('/api/providers').status_code==401
    unlock(client);status=client.get('/api/providers')
    assert status.json()['credential_configured'];assert not status.json()['enabled'];assert KEY not in status.text
    r=client.post('/api/providers/twelvedata/import',json={'instrument':'XAUUSD-TD','limit':100,'end':NOW-60,'rights_confirmed':True,'replace_confirmed':True})
    assert r.status_code==409


def test_historical_pipeline_persists_charts_manifest_archive_and_audit(client,monkeypatch,tmp_path):
    credentials(monkeypatch,tmp_path);monkeypatch.setenv('TWELVEDATA_ENABLED','true');monkeypatch.setenv('MARKET_ARCHIVE_DIR',str(tmp_path/'archive'))
    monkeypatch.setattr(provider_api,'_last_attempt',-1000)
    async def fake(key,instrument,limit,end,now):
        assert key==KEY;return normalize(PAYLOAD,instrument,NOW)
    monkeypatch.setattr(provider_api,'retrieve',fake)
    unlock(client)
    r=client.post('/api/providers/twelvedata/import',json={'instrument':'XAUUSD-TD','limit':100,'end':NOW-60,'rights_confirmed':True,'replace_confirmed':True})
    assert r.status_code==200,r.text
    assert r.json()['rows']==2;assert not r.json()['live'];assert KEY not in r.text
    result=client.get('/api/candles/XAUUSD-TD?timeframe=1m').json()
    assert result['dataset']['provider_symbol']=='XAU/USD';assert len(result['candles'])==2
    assert result['quality']['state']=='WAIT'
    assert len(list((tmp_path/'archive').glob('*.json')))==1
    audit=client.get('/api/audit');assert KEY not in audit.text
    assert any(r['action']=='provider.historical_import' for r in audit.json())
    assert client.post('/api/providers/twelvedata/import',json={'instrument':'XAUUSD-TD','limit':100,'end':NOW-60,'rights_confirmed':True,'replace_confirmed':True}).status_code==429


def test_wrong_instrument_and_missing_rights_are_denied(client,monkeypatch):
    monkeypatch.setenv('TWELVEDATA_ENABLED','true');unlock(client)
    body={'instrument':'NDX-IMPORT','limit':100,'end':NOW-60,'rights_confirmed':True,'replace_confirmed':True}
    assert client.post('/api/providers/twelvedata/import',json=body).status_code==422
    body.update(instrument='XAUUSD-TD',rights_confirmed=False)
    assert client.post('/api/providers/twelvedata/import',json=body).status_code==422
