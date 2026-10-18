"""Verify a private server using the official MCP HTTP client. Never prints tokens."""
import argparse
import asyncio
import getpass
import uuid
from urllib.parse import urlparse
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def verify(args,token):
    async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=30) as http:
        async with Client(streamable_http_client(args.url,http_client=http),cache=None) as sdk:
            tools=await sdk.list_tools()
            print('MCP connected; available tools:',', '.join(t.name for t in tools.tools))
            result=await sdk.call_tool('get_data_quality_status',{'request':{'instrument':args.instrument}})
            if result.is_error:raise RuntimeError('Chart read was denied or failed')
            print('Authenticated chart read succeeded. This does not verify live prices.')
            if args.verify_drawing:
                identifier='connection-test-'+str(uuid.uuid4())
                payload={'instrument':args.instrument,'id':identifier,'kind':'note','points':[{'time':args.time,'price':args.price}],'text':'AI connector test only — not a market setup','version':0,'idempotency_key':identifier}
                created=await sdk.call_tool('create_chart_drawing',{'request':payload})
                if created.is_error:raise RuntimeError('Drawing test failed; inspect the owner audit log')
                print('AI connection-test note created; its exact coordinates were supplied by you.')
                removed=await sdk.call_tool('delete_chart_drawing',{'request':{'instrument':args.instrument,'id':identifier,'version':1,'idempotency_key':identifier+'-delete'}})
                if removed.is_error:raise RuntimeError('Test note removal failed; delete it from Saved drawings')
                print('Test note removed. Confirm both actions in the owner Audit Log.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True,help='Private HTTPS MCP URL ending /api/mcp')
    parser.add_argument('--instrument',default='XAUUSD-IMPORT')
    parser.add_argument('--verify-drawing',action='store_true',help='Authorize creation and deletion of a connection-test note')
    parser.add_argument('--time',type=int,help='Explicit UTC epoch seconds for the test drawing')
    parser.add_argument('--price',type=float,help='Explicit price coordinate for the test drawing')
    args=parser.parse_args();args.url=args.url.rstrip('/');url=urlparse(args.url)
    if url.username or url.password or url.query or url.fragment or not url.hostname:parser.error('Use a credential-free MCP URL')
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1')):parser.error('Remote MCP requires HTTPS')
    if args.verify_drawing and (args.time is None or args.time<0 or args.price is None):parser.error('Provide --time and --price to explicitly locate the test note')
    token=getpass.getpass('AI bearer token (hidden): ')
    try:asyncio.run(verify(args,token))
    except Exception:
        raise SystemExit('Connection verification failed. Check network reachability, token expiry/scopes, private server status and owner audit logs. No credentials were printed.')
