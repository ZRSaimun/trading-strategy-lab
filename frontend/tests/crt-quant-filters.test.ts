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
 const daily=Array.from({length:25},(_,i)=>make(BASE-(25-i)*24*H,100+i*.1,104+i*.1,99+i*.1,100+i*.1,1440));
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
test('an elapsed but partially observed UTC daily bucket cannot satisfy the 20-day trend requirement',()=>{
 const x=fixture();
 // Exactly 20 earlier days: 19 complete and one elapsed-but-partial day.
 x.daily=x.daily!.slice(-20).map((b,i)=>i===0?{...b,observed_minutes:600}:b);
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.dailyTrend,'INSUFFICIENT_DATA');
});

test('a partial most-recent elapsed day cannot be skipped to borrow older trend context',()=>{
 const x=fixture();
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.dailyTrend,'PASS');
 // An elapsed day with only 600/1440 minutes is missing context, even
 // when twenty older complete days remain and would produce a PASS.
 x.daily=[...x.daily!.slice(0,-1),
  make(BASE-24*H,1,2,0.5,1.2,600)];
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.dailyTrend,'INSUFFICIENT_DATA');
 assert.equal(r.gates.structureShift,'PASS');
 assert.equal(r.eligibleForLiveTrading,false);
});

test('an internal partial day inside the 20-session lookback cannot be laundered by older complete days',()=>{
 const x=fixture();
 x.daily=x.daily!.map((b,i)=>i===18?{...b,observed_minutes:600}:b);
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.dailyTrend,'INSUFFICIENT_DATA');
 assert.equal(r.gates.structureShift,'PASS');
});

test('a partial day strictly before the selected 20 complete daily bars does not contaminate current context',()=>{
 const x=fixture();
 x.daily=x.daily!.map((b,i)=>i===0?{...b,observed_minutes:600}:b);
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.dailyTrend,'PASS');
});

test('stale daily history cannot produce a positive 5/20 trend signal for a newer CRT sweep',()=>{
 const x=fixture();
 // The latest completed daily bucket is now more than three days old.
 x.daily=x.daily!.map(b=>({...b,time:b.time-10*24*H}));
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.dailyTrend,'INSUFFICIENT_DATA');
 assert.equal(r.gates.structureShift,'PASS','independent price evidence is unaffected');
});

test('twenty old scattered daily bars cannot masquerade as a fresh 20-session trend',()=>{
 const x=fixture();
 // Last completed day is recent, but twenty observations span 38 days.
 // This is a calendar/data-quality ambiguity, not a validated trend.
 x.daily=Array.from({length:20},(_,i)=>
  make(BASE-(40-i*2)*24*H,100+i*.1,104+i*.1,99+i*.1,100+i*.1,1440));
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.dailyTrend,
  'INSUFFICIENT_DATA');
});

test('a short closure gap does not automatically discard otherwise fresh daily context',()=>{
 const x=fixture();
 // Last fully observed day closed two days before the sweep, while
 // the 20 complete observations remain within a 30-day window.
 x.daily=Array.from({length:20},(_,i)=>
  make(BASE-(22-i)*24*H,100+i*.1,104+i*.1,99+i*.1,100+i*.1,1440));
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.dailyTrend,'PASS');
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
test('zone first recorded during the sweep cannot certify pre-existing 4H context',()=>{
 const x=fixture();
 // Reference bar closed at 04:00, but the zone was first recorded at 06:00,
 // after the 04:00 sweep began and before its 08:00 close.
 x.zones=[{...x.zones![0],referenceBarTime:BASE,observedAt:BASE+6*H}];
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.matchingZone,'INSUFFICIENT_DATA');
 assert.equal(s.gates.structureShift,'PASS','other gates retain their own causal evidence');
});

test('self-referential sweep candle cannot be used as its own prior zone',()=>{
 const x=fixture();
 // Previously this zone passed: the sweep bar closed at 08:00 and the
 // zone was recorded at exactly that close, then backfilled as context.
 x.zones=[{...x.zones![0],referenceBarTime:BASE+4*H,observedAt:BASE+8*H}];
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
});

test('zone match is frozen at sweep close rather than future 15m confirmation price',()=>{
 const x=fixture();
 // Sweep closes at 104; future 15m shift closes at 109. Only the future
 // price touches this zone. It must not retroactively validate the sweep.
 x.zones=[{...x.zones![0],low:108,high:110}];
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.confirmationPrice,109);
 assert.equal(s.gates.matchingZone,'INSUFFICIENT_DATA');
});

test('4H zone known exactly at sweep open may use its fully closed prior candle',()=>{
 const x=fixture();
 x.zones=[{...x.zones![0],referenceBarTime:BASE,observedAt:BASE+4*H}];
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.matchingZone,'PASS');
});

test('nonfinite zone bounds cannot be treated as verified historical context',()=>{
 const x=fixture();
 x.zones=[{...x.zones![0],high:Number.POSITIVE_INFINITY}];
 assert.equal(screenCrtHypotheses(x).candidates[0].gates.matchingZone,'INSUFFICIENT_DATA');
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
test('zero prior-20 median range cannot create an automatic displacement PASS',()=>{
 const x=fixture();
 // All 20 baseline bars are complete and chronologically valid, but flat.
 // A multiplicative range threshold would otherwise be 1.5 * 0 = 0.
 for(let i=12;i<32;i++){
  Object.assign(x.fifteenMinute[i],make(BASE+i*Q,105,105,105,105,15));
 }
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.structureShift,'PASS','the first observed close still breaks prior highs');
 assert.equal(r.gates.displacement,'INSUFFICIENT_DATA');
 assert.equal(r.confirmationCloseAt,BASE+33*Q);
 assert.match(r.notes.join(' '),/median candle range is zero/);
 assert.equal(r.eligibleForLiveTrading,false);
});
test('median zero with a majority of flat 15m bars remains insufficient',()=>{
 const x=fixture();
 for(let i=12;i<23;i++){
  Object.assign(x.fifteenMinute[i],make(BASE+i*Q,105,105,105,105,15));
 }
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.structureShift,'PASS');
 assert.equal(r.gates.displacement,'INSUFFICIENT_DATA');
});
test('positive prior-20 median retains the configured displacement comparison',()=>{
 const x=fixture();
 // Ten flat candles and ten 2-point ranges yield a positive median of 1.
 for(let i=12;i<22;i++){
  Object.assign(x.fifteenMinute[i],make(BASE+i*Q,105,105,105,105,15));
 }
 const r=screenCrtHypotheses(x).candidates[0];
 assert.equal(r.gates.structureShift,'PASS');
 assert.equal(r.gates.displacement,'PASS');
 const stricter=screenCrtHypotheses({...x,displacementMultiple:8}).candidates[0];
 assert.equal(stricter.gates.displacement,'FAIL','threshold still controls valid positive baselines');
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
 Object.assign(x.fifteenMinute[32],make(BASE+32*Q,105,106,104,105,15));
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
 x.fifteenMinute=x.fifteenMinute.filter((_,i)=>i!==12);
 const later=x.fifteenMinute.find(b=>b.time===BASE+33*Q)!;
 later.open=105;later.close=112;later.high=113;later.low=104;
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
 assert.match(s.notes.join(' '),/preceding 20 contiguous bars is incomplete/);
});

test('a gap inside the next 4H block cannot be counted as a complete negative',()=>{
 const x=fixture();
 Object.assign(x.fifteenMinute[32],make(BASE+32*Q,105,106,104,105,15));
 x.fifteenMinute=x.fifteenMinute.filter((_,i)=>i!==35);
 const s=screenCrtHypotheses(x).candidates[0];
 assert.equal(s.gates.structureShift,'INSUFFICIENT_DATA');
 assert.equal(s.confirmationCloseAt,null);
});

test('truncated future history cannot turn a partial negative into an observed FAIL',()=>{
 const x=fixture();
 Object.assign(x.fifteenMinute[32],make(BASE+32*Q,105,106,104,105,15));
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
