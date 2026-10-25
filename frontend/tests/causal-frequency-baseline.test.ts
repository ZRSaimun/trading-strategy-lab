import {test} from 'node:test';
import assert from 'node:assert/strict';
import {estimateCausalFrequencyBaseline as estimate} from '../lib/causal-frequency-baseline.ts';
import type {ReceivedCompletedCandle} from '../lib/causal-frequency-baseline.ts';
const identity={instrument:'XAUUSD-FIXTURE',provider:'fixture',venue:'fixture',sourceId:'A',priceSide:'bid' as const,seconds:60};
const base=1800000000;
const make=(n:number,price=(i:number)=>100+i):ReceivedCompletedCandle[]=>Array.from({length:n},(_,i)=>({
 identity:{...identity},start:base+i*60,close:price(i),receivedAt:base+(i+1)*60+1,
}));
const clock=(n:number)=>base+n*60+5;
test('multi-horizon smoothed estimates are explicitly offline',()=>{
 const result=estimate(make(800),clock(800));
 assert.equal(result.live,false);assert.equal(result.execution,'NONE');
 assert.equal(result.quoteTimestamp,null);
 assert.deepEqual(result.horizons.map(x=>x.horizon),[1,3,12]);
 for(const x of result.horizons){assert.equal(x.status,'READY_OFFLINE_ONLY');assert.equal(x.samples,60);
  assert.equal(x.up,60);assert.equal(x.probabilityUp,60.5/61);}
});
test('decreasing prices give finite smoothed probability rather than 0',()=>{
 const result=estimate(make(800,i=>1000-i),clock(800));
 for(const x of result.horizons){assert.equal(x.up,0);assert.equal(x.probabilityUp,0.5/61);}
});
test('horizon-specific non-overlapping samples and insufficient abstention',()=>{
 const result=estimate(make(31),clock(31));
 assert.deepEqual(result.horizons.map(x=>x.samples),[30,10,2]);
 assert.deepEqual(result.horizons.map(x=>x.status),['READY_OFFLINE_ONLY','INSUFFICIENT','INSUFFICIENT']);
 assert.equal(result.horizons[1].probabilityUp,null);
});
test('future candle and retroactive issuance are rejected',()=>{
 const candles=make(300);
 assert.throws(()=>estimate(candles,clock(299)));
 assert.throws(()=>estimate(candles,clock(301)));
});
test('missing candle, duplicate and backwards timestamps fail closed',()=>{
 const candles=make(300);
 assert.throws(()=>estimate([...candles.slice(0,100),...candles.slice(101)],clock(300)));
 assert.throws(()=>estimate([...candles.slice(0,100),candles[99],...candles.slice(100)],clock(300)));
 assert.throws(()=>estimate(candles.map((c,i)=>i===10?{...c,receivedAt:c.receivedAt-60}:c),clock(300)));
});
test('mixed identity and bad prices are rejected',()=>{
 const candles=make(300);
 assert.throws(()=>estimate(candles.map((c,i)=>i===5?{...c,identity:{...identity,priceSide:'ask'}}:c),clock(300)));
 assert.throws(()=>estimate(candles.map((c,i)=>i===5?{...c,close:NaN}:c),clock(300)));
 assert.throws(()=>estimate(candles.map((c,i)=>i===5?{...c,close:0}:c),clock(300)));
});
test('delayed historical receipts cannot masquerade as prospective',()=>{
 const candles=make(300);
 assert.throws(()=>estimate(candles.map((c,i)=>i===5?{...c,receivedAt:c.receivedAt+1000}:c),clock(300)));
 assert.throws(()=>estimate(candles,clock(300)+121));
});
test('custom bounds validated and sample limit respected',()=>{
 const candles=make(300);
 const r=estimate(candles,clock(300),{minSamples:10,maxSamples:15});
 assert.deepEqual(r.horizons.map(x=>x.samples),[15,15,15]);
 assert.throws(()=>estimate(candles,clock(300),{minSamples:0}));
 assert.throws(()=>estimate(candles,clock(300),{minSamples:30,maxSamples:20}));
 assert.throws(()=>estimate(candles,clock(300),{maxLagSeconds:-1}));
});
test('input and result identities are not aliased',()=>{
 const candles=make(300);const r=estimate(candles,clock(300));
 r.identity.sourceId='modified';assert.equal(candles[0].identity.sourceId,'A');
});
test('same observed history yields deterministic results',()=>{
 const candles=make(300,i=>100+(i%7));
 assert.deepEqual(estimate(candles,clock(300)),estimate(candles,clock(300)));
});
