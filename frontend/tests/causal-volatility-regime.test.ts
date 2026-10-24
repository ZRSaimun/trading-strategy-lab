import {test} from 'node:test';
import assert from 'node:assert/strict';
import {labelCausalHourlyVolatility} from '../lib/causal-volatility-regime.ts';
import type {Bar} from '../lib/research.ts';

const H=3600,START=Date.UTC(2025,0,6)/1000;
const ID={datasetId:'immutable-archive-A',instrument:'NSXUSD-CFD'};
function bars(n=80,wide=1):Bar[]{
 return Array.from({length:n},(_,i)=>({time:START+i*H,open:100,
  high:100+wide,low:100-wide,close:100,volume:null,observed_minutes:60}));
}
test('warmup uses ATR(14) and 24 PRIOR completed hourly ATR observations',()=>{
 const r=labelCausalHourlyVolatility(bars(40),ID);
 assert.equal(r.labelled,2);assert.equal(r.unlabelled,38);
 assert.equal(r.labels[0].candleOpenAt,START+38*H);
 assert.equal(r.labels[0].observedAt,START+39*H);
 assert.equal(r.labels[0].eligibleFrom,r.labels[0].observedAt);
 assert.equal(r.atrPeriod,14);assert.equal(r.baselineBars,24);
});
test('constant true range is tied at percentile 0.5, not low or high',()=>{
 const r=labelCausalHourlyVolatility(bars(80),ID);
 assert.deepEqual(r.counts,{LOW:0,NORMAL:42,HIGH:0});
 assert.ok(r.labels.every(x=>Math.abs(x.trailingPercentile-.5)<1e-12));
 assert.ok(r.labels.every(x=>Math.abs(x.normalizedAtrBps-200)<1e-10));
});
test('newly widened range is high using only prior completed values',()=>{
 const b=bars(42);b[39].high=110;b[39].low=90;
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labels.find(x=>x.candleOpenAt===b[39].time)?.regime,'HIGH');
});
test('newly narrowed range is low using only prior completed values',()=>{
 const b=bars(42,10);b[39].high=100.1;b[39].low=99.9;
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labels.find(x=>x.candleOpenAt===b[39].time)?.regime,'LOW');
});
test('future appended candles cannot change historical labels',()=>{
 const a=labelCausalHourlyVolatility(bars(50),ID);
 const b=bars(70);b[65].high=150;
 const extended=labelCausalHourlyVolatility(b,ID);
 assert.deepEqual(extended.labels.slice(0,a.labels.length),a.labels);
});
test('missing hourly bar resets warmup, never bridges unknown market closure',()=>{
 const b=bars(90);for(let i=45;i<b.length;i++)b[i].time+=H;
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labelled,7);
 assert.equal(r.labels.at(-1)?.candleOpenAt,b[44].time);
});
test('incomplete hourly bar resets warmup and no synthetic fill',()=>{
 const b=bars(90);b[45].observed_minutes=59;
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labelled,7);
});
test('nonpositive price resets warmup and cannot yield normalized ATR',()=>{
 const b=bars(90);b[45]={...b[45],open:0,low:0,close:0};
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labelled,7);
});
test('rejects duplicate, reversed and malformed timestamps',()=>{
 const a=bars();a[5].time=a[4].time;
 assert.throws(()=>labelCausalHourlyVolatility(a,ID),/Duplicate/);
 const b=bars();b[5].time=b[4].time-H;
 assert.throws(()=>labelCausalHourlyVolatility(b,ID),/Duplicate/);
 const c=bars();c[5].time=NaN;
 assert.throws(()=>labelCausalHourlyVolatility(c,ID),/invalid hourly timestamp/);
});
test('requires exact source identity and bounds inputs',()=>{
 assert.throws(()=>labelCausalHourlyVolatility(bars(),{...ID,datasetId:''}),/identity/);
 assert.throws(()=>labelCausalHourlyVolatility(bars(),{...ID,instrument:' '}),/identity/);
 assert.throws(()=>labelCausalHourlyVolatility(null as unknown as Bar[],ID),/Bounded/);
});
test('partial candle at the tail is never labelled',()=>{
 const b=bars(40);b[39].observed_minutes=59;
 const r=labelCausalHourlyVolatility(b,ID);
 assert.equal(r.labelled,1);assert.equal(r.labels[0].candleOpenAt,b[38].time);
});
test('empty input returns no fabricated volatility regime',()=>{
 const r=labelCausalHourlyVolatility([],ID);
 assert.equal(r.labelled,0);assert.equal(r.unlabelled,0);
 assert.deepEqual(r.counts,{LOW:0,NORMAL:0,HIGH:0});
});
