import {test} from 'node:test';
import assert from 'node:assert/strict';
import {screenCrtHypotheses,completeAggregateWindow,type Context,type Source} from '../lib/crt-quant-filters.ts';
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
 const zones=[{datasetId:source.datasetId,archiveSha256:source.archiveSha256,
  priceSide:'bid' as const,direction:'DEMAND' as const,
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
 assert.equal(s.gates.structureShift,'FAIL','complete 16-bar observation without shift is an observed rejection');
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
 x.daily=[...x.daily!,make(BASE,10000,10002,9999,10001,600)];
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
test('a matching dataset ID with a different immutable archive SHA never validates a 4H zone',()=>{
 const x=fixture();
 x.zones=[{...x.zones![0],archiveSha256:'c'.repeat(64)}];
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.matchingZone,'INSUFFICIENT_DATA');
 assert.equal(s.gates.structureShift,'PASS','other source-independent filters still evaluate');
 const y=fixture();y.source={...source,archiveSha256:'c'.repeat(64)};
 assert.equal(screenCrtHypotheses(y).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
});
test('wrong BID side or fabricated 4H zone reference timestamp cannot validate a zone',()=>{
 const wrongSide=fixture();
 wrongSide.zones=[{...wrongSide.zones![0],priceSide:'ask' as 'bid'}];
 assert.equal(screenCrtHypotheses(wrongSide).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
 const misaligned=fixture();
 misaligned.zones=[{...misaligned.zones![0],referenceBarTime:BASE-4*H+900}];
 assert.equal(screenCrtHypotheses(misaligned).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
 const fractional=fixture();
 fractional.zones=[{...fractional.zones![0],observedAt:BASE+0.5}];
 assert.equal(screenCrtHypotheses(fractional).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
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

test('incomplete first/last imported archive buckets are excluded without hiding valid completed 4H CRT patterns',()=>{
 const x=fixture();
 const baseline=screenCrtHypotheses(x).candidates;
 x.fourHour=[
  make(BASE-4*H,105,106,104,105,80),
  ...x.fourHour,
  make(BASE+8*H,105,106,104,105,60),
 ];
 x.fifteenMinute=[
  make(BASE-Q,105,106,104,105,8),
  ...x.fifteenMinute,
  make(BASE+49*Q,105,106,104,105,4),
 ];
 const h4=completeAggregateWindow(x.fourHour,14400);
 const m15=completeAggregateWindow(x.fifteenMinute,900);
 assert.equal(h4.excludedBoundaryBars,2);
 assert.equal(m15.excludedBoundaryBars,2);
 assert.deepEqual(screenCrtHypotheses({...x,fourHour:h4.bars,fifteenMinute:m15.bars}).candidates,baseline);
});
test('partial candles in the interior cannot be silently removed as missing market observations',()=>{
 const x=fixture();
 x.fifteenMinute[12].observed_minutes=14;
 assert.throws(()=>completeAggregateWindow(x.fifteenMinute,900),/Incomplete internal aggregate/);
 const y=fixture();
 y.fourHour[0].observed_minutes=239;
 y.fourHour[1].observed_minutes=239;
 assert.equal(completeAggregateWindow(y.fourHour,14400).bars.length,0);
});
test('malformed or out-of-order boundary aggregates cannot be laundered by trimming',()=>{
 const x=fixture();
 x.fifteenMinute=[make(BASE-Q,105,100,104,105,8),...x.fifteenMinute];
 assert.throws(()=>completeAggregateWindow(x.fifteenMinute,900),/Invalid aggregate candle/);
 const y=fixture();
 y.fifteenMinute=[make(BASE-Q,105,106,104,105,0),...y.fifteenMinute];
 assert.throws(()=>completeAggregateWindow(y.fifteenMinute,900),/Invalid aggregate candle/);
 const z=fixture();
 z.fifteenMinute=[make(BASE,105,106,104,105,8),...z.fifteenMinute];
 assert.throws(()=>completeAggregateWindow(z.fifteenMinute,900),/Invalid aggregate candle/);
});

test('a complete next 4H window without a directional shift is a negative, not unavailable data',()=>{
 const x=fixture();
 x.fifteenMinute[32]=make(BASE+32*Q,105,106,104,105,15);
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'FAIL');
 assert.equal(s.gates.displacement,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
 assert.match(s.notes.join(' '),/All 16 following 15-minute bars/);
});

test('missing 15m history at first eligible close prevents cherry-picking a later stronger shift',()=>{
 const x=fixture();
 // The first eligible 08:00 bar lacks one of its previous 20 bars. The
 // following 08:15 bar has 20 contiguous prior bars and looks attractive,
 // but an earlier shift could have been hidden by the missing observation.
 x.fifteenMinute.splice(12,1);
 const later=x.fifteenMinute.find(b=>b.time===BASE+33*Q)!;
 later.open=105;later.close=112;later.high=113;later.low=104;
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
 assert.match(s.notes.join(' '),/preceding 20 contiguous bars is incomplete/);
});

test('a gap inside the next 4H block cannot be counted as a complete negative',()=>{
 const x=fixture();
 x.fifteenMinute[32]=make(BASE+32*Q,105,106,104,105,15);
 x.fifteenMinute.splice(35,1);
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
});

test('truncated future history cannot turn a partial negative into an observed FAIL',()=>{
 const x=fixture();
 x.fifteenMinute[32]=make(BASE+32*Q,105,106,104,105,15);
 x.fifteenMinute=x.fifteenMinute.slice(0,38);
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
});

test('the first closed-bar confirmation is stable without later 15m candles',()=>{
 const x=fixture();
 const full=screenCrtHypotheses(x).candidates[0];
 x.fifteenMinute=x.fifteenMinute.slice(0,33);
 const prefix=screenCrtHypotheses(x).candidates[0];
 assert.equal(prefix.gates.structureShift,'PASS');
 assert.equal(prefix.gates.displacement,full.gates.displacement);
 assert.equal(prefix.confirmationCloseAt,full.confirmationCloseAt);
});
