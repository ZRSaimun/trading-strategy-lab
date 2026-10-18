import 'fake-indexeddb/auto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compare,DEFAULTS} from '../lib/backtest.ts';
import {evaluateAlert} from '../lib/alerts.ts';
import {localAPI} from '../lib/local-api.ts';
import {encodeBackup,decodeBackup,validateEntries} from '../lib/workspace-backup.ts';
const put=(body:unknown)=>({method:'PUT',body:JSON.stringify(body)});
const exported=()=>localAPI('/workspace/export',{method:'POST'});
const restore=(text:string,confirmed=true)=>{const form=new FormData();form.set('file',new File([text],'workspace.json',{type:'application/json'}));if(confirmed)form.set('replace_confirmed','true');return localAPI('/workspace/restore',{method:'POST',body:form})};
test('workspace export/restore roundtrip retains candles, sources, drawings, research and watchlist',async()=>{
 const form=new FormData();form.set('instrument','XAUUSD-IMPORT');form.set('source','Deterministic software test fixture (not market data)');form.set('volume_type','tick');form.set('rights_confirmed','true');form.set('file',new File(['time,open,high,low,close,volume\n2024-01-01T00:00:00Z,10,12,9,11,5\n2024-01-01T00:01:00Z,11,13,10,12,6'],'fixture.csv'));
 await localAPI('/import',{method:'POST',body:form});
 await localAPI('/drawings/XAUUSD-IMPORT',put({id:'backup-level',kind:'horizontal',points:[{time:1704067200,price:10}],version:0,text:'Fixture only'}));
 await localAPI('/research/journal',put({id:'fixture-entry',title:'Software fixture',created_at:1704067200,payload:{instrument:'XAUUSD-IMPORT',runId:'fixture-run',notes:'Software fixture',entryStatus:'SIMULATED ONLY',trade:{entryAt:1704067200,exitAt:1704067260,pnl:0,r:0,reason:'fixture',verification:'SIMULATED OHLC ONLY'}}}));
 await localAPI('/watchlist',put({instruments:['XAUUSD-IMPORT']}));
 const candles=Array.from({length:60},(_,i)=>({time:1704067200+i*60,open:10+i/10,high:12+i/10,low:9+i/10,close:11+i/10,volume:2,observed_minutes:1}));
 const reports=compare(candles,{...DEFAULTS,barSeconds:60});
 await localAPI('/research/backtests',put({id:'fixture-run',title:'Fixture run',created_at:1704067200,payload:{instrument:'XAUUSD-IMPORT',source:'Software fixture',datasetHash:'a'.repeat(64),window:{start:candles[0].time,end:candles.at(-1)!.time,bars:60},reports,splits:[{name:'Fixture',reports}],notes:'Not market data',candles}}));
 const rule={id:'fixture-rule',title:'Fixture rule',created_at:1704067200,payload:{instrument:'XAUUSD-IMPORT',timeframe:'1m',kind:'CLOSE ABOVE' as const,level:11,acceptance:1,enabled:true,version:1}};
 await localAPI('/research/alert-rules',put(rule));
 const event=evaluateAlert(rule,candles.slice(0,2),{instrument:'XAUUSD-IMPORT',timeframe:'1m',source:'Software fixture',datasetHash:'a'.repeat(64)})!;
 assert.ok(event);await localAPI('/research/alert-events',put(event));
 const backup=await exported();const original=await localAPI('/candles/XAUUSD-IMPORT?timeframe=1m');
 await localAPI('/drawings/XAUUSD-IMPORT/backup-level?version=1',{method:'DELETE'});await localAPI('/watchlist',put({instruments:[]}));
 await restore(JSON.stringify(backup));
 assert.deepEqual(await localAPI('/candles/XAUUSD-IMPORT?timeframe=1m'),original);
 assert.equal((await localAPI('/drawings/XAUUSD-IMPORT'))[0].text,'Fixture only');assert.equal((await localAPI('/research/journal'))[0].id,'fixture-entry');assert.deepEqual(await localAPI('/watchlist'),['XAUUSD-IMPORT']);
 assert.deepEqual((await localAPI('/research/backtests'))[0].payload.reports,reports);assert.equal((await localAPI('/research/alert-rules'))[0].id,rule.id);assert.equal((await localAPI('/research/alert-events'))[0].id,event.id);
 assert.equal((await localAPI('/audit'))[0].action,'workspace.restore');
});
test('corruption and missing replacement confirmation never modify storage',async()=>{
 const before=await exported();
 await assert.rejects(restore(JSON.stringify(before),false),/Confirm replacement/);
 const corrupt=structuredClone(before);corrupt.entries.find((e:any)=>e.key==='watchlist').value=[];
 await assert.rejects(restore(JSON.stringify(corrupt)),/checksum/);
 await assert.rejects(restore('{bad json'),/Invalid workspace/);
 assert.deepEqual((await exported()).entries,before.entries);
});
test('unsupported formats, duplicate keys, substituted instruments and bad coordinates are rejected',async()=>{
 assert.throws(()=>validateEntries([{key:'dataset:NQ',value:{}}]));
 assert.throws(()=>validateEntries([{key:'watchlist',value:[]},{key:'watchlist',value:[]}]));
 assert.throws(()=>validateEntries([{key:'watchlist',value:['CME:NQ']} ]));
 assert.throws(()=>validateEntries([{key:'drawings:XAUUSD-IMPORT',value:[{id:'bad',kind:'horizontal',version:1,text:'',points:[{time:0,price:'10'}]}]}]));
 await assert.rejects(decodeBackup(JSON.stringify({format:'trading-strategy-lab-workspace',version:9,entries:[]})));
 const b=await exported();const dataset=b.entries.find((e:any)=>e.key==='dataset:XAUUSD-IMPORT');dataset.value.rows[0].high=1;
 await assert.rejects(encodeBackup(b.entries),/OHLC/);
});
test('synchronous storage failure after clear rolls back all changes and later restore works',async()=>{
 const before=await exported(),empty=await encodeBackup([{key:'watchlist',value:[]}]);
 const original=IDBObjectStore.prototype.put;
 IDBObjectStore.prototype.put=function(){throw new DOMException('Simulated quota failure','QuotaExceededError')};
 try{await assert.rejects(restore(JSON.stringify(empty)),/Simulated quota/)}finally{IDBObjectStore.prototype.put=original}
 assert.deepEqual((await exported()).entries,before.entries);
 await restore(JSON.stringify(before));assert.deepEqual(await localAPI('/watchlist'),['XAUUSD-IMPORT']);
});
test('restore replaces rather than merges records and export is ordered after earlier writes',async()=>{
 const save=localAPI('/watchlist',put({instruments:['NDX-IMPORT']})),snapshot=exported();await save;
 assert.deepEqual((await snapshot).entries.find((e:any)=>e.key==='watchlist').value,['NDX-IMPORT']);
 const blank=await encodeBackup([]);await restore(JSON.stringify(blank));assert.deepEqual(await localAPI('/drawings/XAUUSD-IMPORT'),[]);assert.deepEqual(await localAPI('/research/journal'),[]);assert.equal((await localAPI('/candles/XAUUSD-IMPORT')).quality.state,'NO DATA');assert.equal((await localAPI('/audit')).length,1);
});

test('asynchronous transaction abort also preserves the previous workspace',async()=>{
 const before=await exported(),replacement=await encodeBackup([{key:'watchlist',value:['NDX-IMPORT']}]);
 const original=IDBObjectStore.prototype.put;
 IDBObjectStore.prototype.put=function(value:any,key?:IDBValidKey){const result=original.call(this,value,key),tx=this.transaction;queueMicrotask(()=>{try{tx.abort()}catch{}});return result};
 try{await assert.rejects(restore(JSON.stringify(replacement)),/Restore failed/)}finally{IDBObjectStore.prototype.put=original}
 assert.deepEqual((await exported()).entries,before.entries);
});
