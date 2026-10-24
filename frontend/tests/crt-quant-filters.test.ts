import {test} from 'node:test';
import assert from 'node:assert/strict';
import {screenCrtHypotheses,type Context,type Source} from '../lib/crt-quant-filters.ts';
import type {Bar} from '../lib/research.ts';

const H=3600,Q=900,BASE=Date.UTC(2026,9,20)/1000;
const source:Source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'NSXUSD-CFD',provider:'owner-authorized-archive',
 priceSide:'bid',volumeType:'exchange',volumeVerified:true};
const make=(time:number,open:number,high:number,low:number,close:number,mins:number,volume=100):Bar=>
 ({time,open,high,low,close,observed_minutes:mins,volume});
function fixture():Context{
 const fourHour=[
  make(BASE,105,110,100,105,240),
  make(BASE+4*H,104,109,98.5,104,240)
 ];
 const fifteenMinute=Array.from({length:49},(_,i)=>make(BASE+i*Q,105,106,104,105,15));
 const signal=fifteenMinute[32];
 signal.open=105;signal.close=109;signal.high=110;signal.low=104;signal.volume=200;
 const daily=Array.from({length:25},(_,i)=>make(BASE-(25-i)*24*H,100+i*.1,104+i*.1,99+i*.1,100+i*.1,1000));
 const zones=[{datasetId:source.datasetId,direction:'DEMAND' as const,
  low:100,high:110,observedAt:BASE,referenceBarTime:BASE-4*H}];
 return {fourHour,fifteenMinute,daily,source,zones};
}
test('causal 4H sweep and subsequent 15m close passes proposed price/volume/proxy gates',()=>{
 const x=screenCrtHypotheses(fixture());
 assert.equal(x.candidates.length,1);
 const s=x.candidates[0];
 assert.equal(s.direction,'BULLISH');
 assert.equal(s.sweepDepthFraction,.15);
 assert.equal(s.sweepCloseAt,BASE+8*H);
 assert.equal(s.confirmationCloseAt,BASE+8*H+Q);
 assert.equal(s.gates.sweepDepth,'PASS');
 assert.equal(s.gates.structureShift,'PASS');
 assert.equal(s.gates.displacement,'PASS');
 assert.equal(s.gates.volume,'PASS');
 assert.equal(s.gates.dailyTrend,'PASS');
 assert.equal(s.gates.matchingZone,'PASS');
 assert.equal(s.gates.newsCalendar,'INSUFFICIENT_DATA');
 assert.equal(s.eligibleForLiveTrading,false);
});
test('a manipulation deeper than 40% of prior 4H range is rejected',()=>{
 const x=fixture();x.fourHour[1].low=95;
 const v=screenCrtHypotheses(x).candidates[0];
 assert.equal(v.gates.sweepDepth,'FAIL');
 assert.equal(v.sweepDepthFraction,.5);
});
test('15m shift cannot be validated from a bar closing BEFORE the 4H manipulation is complete',()=>{
 const x=fixture();
 const before=x.fifteenMinute[31];
 before.open=105;before.close=110;before.high=111;before.low=104;before.volume=500;
 // The first shift after 08:00 now cannot beat the 07:45 spike.
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
});
test('verified volume missing means insufficient: never turn placeholders into volume confirmation',()=>{
 const x=fixture();
 x.source={...source,volumeType:'unverified',volumeVerified:false};
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.volume,'INSUFFICIENT_DATA');
 assert.equal(r.gates.structureShift,'PASS');
 const y=fixture();y.fifteenMinute[32].volume=0;
 assert.equal(screenCrtHypotheses(y).candidates[0].gates.volume,'INSUFFICIENT_DATA');
});
test('daily trend uses only completed daily history, never current incomplete daily candle',()=>{
 const x=fixture();
 const original=screenCrtHypotheses(x).candidates[0].gates.dailyTrend;
 x.daily!.push(make(BASE,10000,10002,9999,10001,600));
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.dailyTrend,original);
 const missing=fixture();missing.daily=missing.daily!.slice(0,15);
 assert.equal(screenCrtHypotheses(missing).candidates[0].gates.dailyTrend,'INSUFFICIENT_DATA');
});
test('no source-linked pre-existing 4H reference means supply/demand gate stays unavailable',()=>{
 const x=fixture();x.zones=[{...x.zones![0],observedAt:BASE+9*H}];
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.matchingZone,'INSUFFICIENT_DATA');
 const y=fixture();y.zones=[{...y.zones![0],datasetId:'c'.repeat(64)}];
 assert.equal(screenCrtHypotheses(y).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
});
test('the range median uses only 20 preceding contiguous 15m candles, not future volatility',()=>{
 const x=fixture();
 const before=screenCrtHypotheses(x).candidates[0];
 // Outcomes after first closed confirmation may not change its timing.
 x.fifteenMinute.slice(33).forEach(b=>{b.high=10000;b.close=9000;b.open=9000;b.low=8000});
 const after=screenCrtHypotheses(x).candidates[0];
 assert.deepEqual(after.gates,before.gates);
 assert.equal(after.confirmationCloseAt,before.confirmationCloseAt);
});
test('malformed price bars, time alignment and source identity fail closed',()=>{
 const x=fixture();x.fifteenMinute[1].observed_minutes=14;
 assert.throws(()=>screenCrtHypotheses(x),/Invalid, incomplete/);
 const y=fixture();y.fourHour[1].time+=Q;
 assert.throws(()=>screenCrtHypotheses(y),/Invalid, incomplete/);
 const z=fixture();z.source={...source,priceSide:'ask' as 'bid'};
 assert.throws(()=>screenCrtHypotheses(z),/Invalid source/);
 const w=fixture();w.sweepMaxFraction=1.1;
 assert.throws(()=>screenCrtHypotheses(w),/Invalid source/);
});
