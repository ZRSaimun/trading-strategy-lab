import 'fake-indexeddb/auto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {localAPI} from '../lib/local-api.ts';
const put=(body:unknown)=>({method:'PUT',body:JSON.stringify(body)});
test('concurrent drawing saves retain both drawings and their audit records',async()=>{
 const make=(id:string)=>({id,kind:'horizontal',points:[{time:1700000000,price:2000}],version:0,text:id});
 await Promise.all([localAPI('/drawings/XAUUSD-IMPORT',put(make('concurrent-a'))),localAPI('/drawings/XAUUSD-IMPORT',put(make('concurrent-b')))]);
 const drawings=await localAPI('/drawings/XAUUSD-IMPORT');assert.equal(drawings.length,2);
 const audit=await localAPI('/audit');assert.equal(audit.filter((x:any)=>x.action==='drawing.save').length,2);
});
test('failed mutation does not poison the queue; instrument drawings stay separate',async()=>{
 await assert.rejects(localAPI('/drawings/XAUUSD-IMPORT',put({id:'concurrent-a',kind:'horizontal',points:[{time:1700000000,price:2000}],version:0,text:'stale'})),/version conflict/);
 await localAPI('/drawings/NDX-IMPORT',put({id:'nasdaq-only',kind:'horizontal',points:[{time:1700000000,price:30000}],version:0,text:'NDX'}));
 assert.equal((await localAPI('/drawings/NDX-IMPORT')).length,1);assert.equal((await localAPI('/drawings/XAUUSD-IMPORT')).length,2);
});
test('simultaneous duplicate replay events are saved and audited only once',async()=>{
 const event={id:'event-duplicate',title:'Historical observation',created_at:1700000000,payload:{mode:'HISTORICAL REPLAY'}};
 await Promise.all([localAPI('/research/alert-events',put(event)),localAPI('/research/alert-events',put(event))]);
 const events=await localAPI('/research/alert-events');assert.equal(events.length,1);
 const audit=await localAPI('/audit');assert.equal(audit.filter((x:any)=>x.action==='research.alert-events.save').length,1);
});
