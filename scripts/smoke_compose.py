"""Isolated Docker stack acceptance test. Requires Docker; uses no real data or keys."""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from argon2 import PasswordHasher

root=Path(__file__).resolve().parents[1]
project='tsl-smoke-'+uuid.uuid4().hex[:10]
password=secrets.token_urlsafe(32)
with tempfile.TemporaryDirectory(prefix='tsl-smoke-') as directory:
    envfile=Path(directory)/'smoke.env'
    fd=os.open(envfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write("POSTGRES_PASSWORD="+secrets.token_hex(32)+"\nOWNER_PASSWORD_HASH='"+PasswordHasher().hash(password)+"'\nPUBLIC_ORIGIN=http://localhost:3000\nCOOKIE_SECURE=false\n")
    compose=['docker','compose','--project-name',project,'--env-file',str(envfile),'-f',str(root/'compose.yaml')]
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path,method='GET',data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request('http://127.0.0.1:3000'+path,data=None if data is None else json.dumps(data).encode(),headers=headers,method=method)
        with opener.open(req,timeout=15) as response:return json.load(response)
    try:
        subprocess.run(compose+['up','--build','-d'],check=True)
        ready=False
        for _ in range(90):
            try:
                with opener.open('http://127.0.0.1:3000',timeout=3) as response:ready=response.status==200
                if ready:break
            except (OSError,urllib.error.URLError):pass
            time.sleep(2)
        if not ready:raise RuntimeError('Web service did not become ready')
        try:request('/api/instruments')
        except urllib.error.HTTPError as e:assert e.code==401
        else:raise AssertionError('Unauthenticated data access was allowed')
        request('/api/login','POST',{'password':password})
        assert request('/api/candles/XAUUSD-IMPORT')['quality']['state']=='NO DATA'
        boundary='tsl-'+uuid.uuid4().hex
        csv='time,open,high,low,close\n2024-01-01T00:00:00Z,1,3,1,2\n2024-01-01T00:01:00Z,2,4,1,3\n2024-01-01T00:02:00Z,3,5,2,4\n'
        fields={'instrument':'XAUUSD-IMPORT','source':'Deterministic software fixture — not market data','rights_confirmed':'true','volume_type':'none'}
        parts=[]
        for key,value in fields.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n')
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="software-fixture.csv"\r\nContent-Type: text/csv\r\n\r\n{csv}\r\n--{boundary}--\r\n')
        req=urllib.request.Request('http://127.0.0.1:3000/api/import',data=''.join(parts).encode(),headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        with opener.open(req,timeout=15) as response:assert json.load(response)['rows']==3
        assert len(request('/api/candles/XAUUSD-IMPORT?timeframe=1m')['candles'])==3
        issued=request('/api/ai/tokens','POST',{'label':'Isolated Docker smoke test','scopes':['charts:read','drawings:write'],'expires_in_hours':1})
        token=issued['token']
        args={'instrument':'XAUUSD-IMPORT','id':'docker-connection-test','kind':'note','points':[{'time':1704067200,'price':1}],'text':'Software connection test only — not market data','version':0,'idempotency_key':'docker-create'}
        created=request('/api/ai/tools/create_chart_drawing','POST',args,token)
        assert created['provenance']=='ai' and created['version']==1
        assert request('/api/drawings/XAUUSD-IMPORT')[0]['id']=='docker-connection-test'
        assert any(r['action']=='ai.create_chart_drawing' for r in request('/api/audit'))
        # Exercise the actual HTTP reverse proxy and the official MCP SDK transport.
        import asyncio
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        async def mcp_read():
            async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token}) as http:
                async with Client(streamable_http_client('http://127.0.0.1:3000/api/mcp',http_client=http),cache=None) as sdk:
                    result=await sdk.call_tool('get_candles',{'request':{'instrument':'XAUUSD-IMPORT','limit':1}})
                    assert not result.is_error
        asyncio.run(mcp_read())
        request('/api/ai/tokens/'+issued['id'],'DELETE')
        try:request('/api/ai/tools/list_instruments','POST',{},token)
        except urllib.error.HTTPError as e:assert e.code==401
        else:raise AssertionError('Revoked token was accepted')
        print('Docker smoke passed: owner login, guarded data, AI drawing/audit, SDK HTTP proxy and revocation. No live feed was tested.')
    finally:
        # Only this randomly named disposable project's resources are removed.
        subprocess.run(compose+['down','--volumes','--remove-orphans'],check=False)
