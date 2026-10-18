"""Official SDK transport sharing the strictly scoped application tool service."""
import os
from urllib.parse import urlparse
from mcp.server.mcpserver import MCPServer, Context
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi import HTTPException
from .ai_access import TOOLS, Empty, execute, transport_auth



def register(mcp,name,model,description):
    if model is Empty:
        async def handler(ctx):
            return await run_in_threadpool(execute,name,{},ctx.headers or {})
        handler.__annotations__={'ctx':Context,'return':dict|list}
    else:
        async def handler(request,ctx):
            return await run_in_threadpool(execute,name,request.model_dump(),ctx.headers or {})
        handler.__annotations__={'request':model,'ctx':Context,'return':dict|list}
    mcp.tool(name=name,description=description)(handler)

def build_transport():
    mcp=MCPServer('Trading Strategy Lab',version='0.11.0',instructions='Private historical research only. Imported candles are not executable live quotes. AI drawings are marked. No orders or credentials are exposed.')
    for name,(model,scope,description) in TOOLS.items():register(mcp,name,model,description)
    origin=os.getenv('PUBLIC_ORIGIN','http://localhost:3000')
    security=TransportSecuritySettings(allowed_hosts=list(set([urlparse(origin).netloc,'localhost','localhost:*','127.0.0.1','127.0.0.1:*','api:8000'])),allowed_origins=[origin])
    transport=mcp.streamable_http_app(streamable_http_path='/',stateless_http=True,json_response=True,transport_security=security,max_request_body_size=1_000_000)
    return mcp,transport

class AuthenticatedMCP:
    transport=None
    def configure(self):
        server,self.transport=build_transport()
        return server
    async def __call__(self,scope,receive,send):
        if scope['type']=='http':
            try:transport_auth(Headers(scope=scope))
            except HTTPException as e:
                await JSONResponse({'detail':e.detail},status_code=e.status_code,headers={'Cache-Control':'no-store','WWW-Authenticate':'Bearer'})(scope,receive,send)
                return
        if self.transport is None:
            await JSONResponse({'detail':'MCP service not started'},status_code=503)(scope,receive,send);return
        await self.transport(scope,receive,send)

mcp_app=AuthenticatedMCP()
