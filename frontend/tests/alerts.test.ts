import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evaluateAlert,evaluateAdvance,validateRule,type AlertRule} from '../lib/alerts.ts';
import type {Bar} from '../lib/research.ts';
const context={instrument:'XAUUSD-IMPORT',timeframe:'1m',source:'software-test-fixture',datasetHash:'a'.repeat(64)};
const rule:AlertRule={id:'rule-1',title:'Research level',created_at:1,payload:{instrument:context.instrument,timeframe:'1m',kind:'CLOSE ABOVE',level:10,acceptance:2,enabled:true,version:1}};
const b=(n:number,close:number):Bar=>({time:1700000040+n*60,open:close,high:close+1,low:close-1,close,volume:null,observed_minutes:1});
test('acceptance waits for all closing evidence and never confirms a demo buy',()=>{
 const bars=[b(0,9),b(1,11),b(2,12)];assert.equal(evaluateAlert(rule,bars.slice(0,2),context),null);
 const event=evaluateAlert(rule,bars,context)!;assert.ok(event);assert.equal(event.payload.observedAt,bars[2].time+60);assert.equal(event.payload.state,'WATCHING LEVEL');assert.equal(event.payload.execution,'NONE');assert.equal(event.payload.live,false);assert.equal(event.payload.quoteTimestamp,null);
 assert.equal(evaluateAlert(rule,[...bars,b(3,13)],context),null);
});
test('stable event keys deduplicate rewind, distinguish dataset replacement and rule revisions',()=>{
 const bars=[b(0,9),b(1,11),b(2,12)],event=evaluateAlert(rule,bars,context)!;
 assert.equal(evaluateAlert(rule,bars,context,new Set([event.id])),null);
 assert.notEqual(evaluateAlert(rule,bars,{...context,datasetHash:'b'.repeat(64)})!.id,event.id);
 assert.notEqual(evaluateAlert({...rule,payload:{...rule.payload,version:2}},bars,context)!.id,event.id);
});
test('wrong instrument, disabled rules, partial data, gaps and no source cannot alert',()=>{
 const bars=[b(0,9),b(1,11),b(2,12)];
 assert.equal(evaluateAlert(rule,bars,{...context,instrument:'NDX-IMPORT'}),null);
 assert.equal(evaluateAlert({...rule,payload:{...rule.payload,enabled:false}},bars,context),null);
 assert.equal(evaluateAlert(rule,bars.map((x,i)=>({...x,observed_minutes:i===1?0:1})),context),null);
 assert.equal(evaluateAlert(rule,[bars[0],bars[1],{...bars[2],time:bars[2].time+60}],context),null);
 assert.equal(evaluateAlert(rule,bars,{...context,datasetHash:''}),null);
});
test('FVG is reported only at third-bar close and input prefix is sufficient',()=>{
 const r={...rule,payload:{...rule.payload,kind:'BULLISH FVG' as const}};
 const bars=[b(0,10),b(1,12),b(2,15)];assert.equal(evaluateAlert(r,bars.slice(0,2),context),null);
 const event=evaluateAlert(r,bars,context)!;assert.ok(event);assert.equal(event.payload.state,'PATTERN OBSERVED');assert.deepEqual(event.payload.evidence,bars.map(x=>x.time));
});
test('sweeps cannot reuse a confirmed swing from before a missing-data gap',()=>{
 const r={...rule,payload:{...rule.payload,kind:'SELL-SIDE SWEEP' as const}};
 const bars=[b(0,12),b(1,11),b(2,5),b(3,11),b(4,12),...Array.from({length:10},(_,i)=>b(i+10,12)),{...b(20,12),low:3}];
 assert.equal(evaluateAlert(r,bars,context),null);
});
test('invalid thresholds and unsupported timeframes are rejected',()=>{
 assert.throws(()=>validateRule({...rule,payload:{...rule.payload,level:NaN}}));
 assert.throws(()=>validateRule({...rule,payload:{...rule.payload,timeframe:'1M'}}));
});

test('batched replay advances check every newly revealed candle without backfilling on rewind',()=>{
 const bars=[b(0,9),b(1,11),b(2,12),b(3,13)];
 const events=evaluateAdvance([rule],bars,1,4,context,new Set());assert.equal(events.length,1);assert.equal(events[0].payload.observedAt,bars[2].time+60);
 assert.equal(evaluateAdvance([rule],bars,4,2,context,new Set()).length,0);
 assert.equal(evaluateAdvance([rule],bars,1,4,context,new Set([events[0].id])).length,0);
});
