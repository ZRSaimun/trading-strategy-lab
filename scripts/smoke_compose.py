"""Isolated Docker stack acceptance test. Requires Docker; uses no real data or keys."""
import http.cookiejar
import argparse
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
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--combined',action='store_true',help='Test the memory-limited free-cloud image and private schema')
combined=parser.parse_args().combined
project='tsl-smoke-'+uuid.uuid4().hex[:10]
password=secrets.token_urlsafe(32)
with tempfile.TemporaryDirectory(prefix='tsl-smoke-') as directory:
    envfile=Path(directory)/'smoke.env'
    fd=os.open(envfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write("POSTGRES_PASSWORD="+secrets.token_hex(32)+"\nOWNER_PASSWORD_HASH='"+PasswordHasher().hash(password)+"'\nPUBLIC_ORIGIN=http://localhost:3000\nCOOKIE_SECURE=false\n")
    compose=['docker','compose','--project-name',project,'--env-file',str(envfile),'-f',str(root/('deploy/compose.free-test.yaml' if combined else 'compose.yaml'))]
    class LocalFixtureCookiePolicy(http.cookiejar.DefaultCookiePolicy):
        def return_ok_secure(self,cookie,request):
            # The container fixture has no TLS terminator. Production cookies stay Secure.
            if combined and request.host=='127.0.0.1:3000':return True
            return super().return_ok_secure(cookie,request)
    jar=http.cookiejar.CookieJar(policy=LocalFixtureCookiePolicy())
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def request(path,method='GET',data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request('http://127.0.0.1:3000'+path,data=None if data is None else json.dumps(data).encode(),headers=headers,method=method)
        with opener.open(req,timeout=15) as response:return json.load(response)
    def import_fixture(instrument,csv):
        boundary='tsl-'+uuid.uuid4().hex
        fields={'instrument':instrument,'source':'Deterministic software fixture — not market data','rights_confirmed':'true','volume_type':'none'}
        parts=[]
        for key,value in fields.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n')
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="software-fixture.csv"\r\nContent-Type: text/csv\r\n\r\n{csv}\r\n--{boundary}--\r\n')
        req=urllib.request.Request('http://127.0.0.1:3000/api/import',data=''.join(parts).encode(),headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        with opener.open(req,timeout=30) as response:return json.load(response)
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
        if combined:
            assert next(c for c in jar if c.name=='tsl_session').secure
            assert request('/api/health')['profile']=='free-cloud'
        assert request('/api/candles/XAUUSD-IMPORT')['quality']['state']=='NO DATA'
        csv='time,open,high,low,close\n2024-01-01T00:00:00Z,1,3,1,2\n2024-01-01T00:01:00Z,2,4,1,3\n2024-01-01T00:02:00Z,3,5,2,4\n'
        assert import_fixture('XAUUSD-IMPORT',csv)['rows']==3
        assert len(request('/api/candles/XAUUSD-IMPORT?timeframe=1m')['candles'])==3
        if combined:
            from datetime import datetime,timezone,timedelta
            start=datetime(2024,1,2,tzinfo=timezone.utc)
            csv='time,open,high,low,close\n'+''.join((start+timedelta(minutes=i)).isoformat()+',1,3,1,2\n' for i in range(5000))
            assert import_fixture('NDX-IMPORT',csv)['rows']==5000
            result=request('/api/candles/NDX-IMPORT?timeframe=1m')
            assert result['has_more'] and len(result['candles'])==2000
            assert result['dataset']['rows']==5000
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
        if combined:
            schema_sql="SELECT count(*) FROM pg_tables WHERE schemaname='tsl_private' AND rowsecurity=true; SELECT has_schema_privilege('anon','tsl_private','USAGE'),has_schema_privilege('authenticated','tsl_private','USAGE'); SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('records','candles','audit');"
            schema=subprocess.run(compose+['exec','-T','db','psql','-U','lab','-d','lab','-Atc',schema_sql],check=True,capture_output=True,text=True).stdout.strip()
            assert schema=='4\nf|f\n0','Private schema isolation or RLS did not match'
            # A restart must preserve data/drawings in Postgres and run migrations idempotently.
            subprocess.run(compose+['restart','web'],check=True)
            for _ in range(60):
                try:
                    if request('/api/health')['status']=='ok':break
                except (OSError,urllib.error.URLError):pass
                time.sleep(2)
            else:raise AssertionError('Combined service did not recover after restart')
            assert len(request('/api/candles/XAUUSD-IMPORT?timeframe=1m')['candles'])==3
            assert request('/api/drawings/XAUUSD-IMPORT')[0]['provenance']=='ai'
            container=subprocess.run(compose+['ps','-q','web'],check=True,capture_output=True,text=True).stdout.strip()
            memory=subprocess.run(['docker','stats','--no-stream','--format','{{.MemUsage}}',container],check=True,capture_output=True,text=True).stdout.strip()
            print('Combined fixture memory after restart:',memory)
            info=json.loads(subprocess.run(['docker','inspect',container],check=True,capture_output=True,text=True).stdout)[0]
            assert info['HostConfig']['Memory']==512*1024*1024 and not info['State']['OOMKilled']
        dump=subprocess.run(compose+['exec','-T','db','pg_dump','-U','lab','-d','lab','-Fc'],check=True,capture_output=True).stdout
        subprocess.run(compose+['exec','-T','db','createdb','-U','lab','lab_restore_smoke'],check=True,capture_output=True)
        subprocess.run(compose+['exec','-T','db','pg_restore','-U','lab','-d','lab_restore_smoke','--no-owner','--exit-on-error'],input=dump,check=True,capture_output=True)
        sql="SELECT (SELECT count(*) FROM candles),(SELECT count(*) FROM records WHERE key LIKE 'drawing:%'),(SELECT count(*) FROM audit WHERE action='ai.create_chart_drawing');"
        restored=subprocess.run(compose+['exec','-T','db','psql','-U','lab','-d','lab_restore_smoke','-Atc',sql],check=True,capture_output=True,text=True).stdout.strip()
        assert restored==('5003|1|1' if combined else '3|1|1'),'Restored fixture candles, drawing or audit record did not match'
        # Simulate a snapshot taken before revocation, then apply the documented recovery policy.
        reset="UPDATE records SET value=jsonb_set(value::jsonb, '{revoked}', 'false'::jsonb)::text WHERE key LIKE 'ai-token:%';"
        invalidate="BEGIN; DELETE FROM records WHERE key LIKE 'session:%'; UPDATE records SET value=jsonb_set(value::jsonb, '{revoked}', 'true'::jsonb)::text WHERE key LIKE 'ai-token:%'; COMMIT;"
        for sql in (reset,invalidate):subprocess.run(compose+['exec','-T','db','psql','-U','lab','-d','lab_restore_smoke','-v','ON_ERROR_STOP=1','-c',sql],check=True,capture_output=True)
        check="SELECT (SELECT count(*) FROM records WHERE key LIKE 'session:%'),(SELECT count(*) FROM records WHERE key LIKE 'ai-token:%' AND (value::jsonb->>'revoked')::boolean=false);"
        state=subprocess.run(compose+['exec','-T','db','psql','-U','lab','-d','lab_restore_smoke','-Atc',check],check=True,capture_output=True,text=True).stdout.strip()
        assert state=='0|0','Restored authentication must be invalidated before reopening access'

        print('Docker smoke passed: owner login, guarded data, AI drawing/audit, SDK HTTP proxy, revocation and disposable database backup/restore. No live feed was tested.')
    finally:
        # Only this randomly named disposable project's resources are removed.
        subprocess.run(compose+['down','--volumes','--remove-orphans'],check=False)
