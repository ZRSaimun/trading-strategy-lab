import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID-only geometry. Not broker quotes or verified volume.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`a later completed ${direction} non-touch cannot repair a missing middle wait hour`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   // Hour 24 missing. Hour 25 is observed, but does not touch midpoint (~101).
   {time:25*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   {time:25*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const before=studyHourlyFvgMidpointAsOf(bars.slice(0,-1),source,24*H);
  const after=studyHourlyFvgMidpointAsOf(bars,source,26*H);
  const pick=(r:typeof before)=>r.observations.find(
   o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.equal(pick(before)?.firstTouchCensorReason,'RIGHT_CENSORED');
  const o=pick(after);
  assert.ok(o);
  assert.equal(o.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(o.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(o.firstTouchCensorMissingHourSlots,1);
  // Only hour 23 was observed after formation. Missing hour 24 must not
  // inflate the observed risk set or be counted as a known no-touch.
  assert.equal(o.firstTouchObservedWaitBars,1);
  assert.equal(o.firstTouchCensorObservedAt,26*H);
  assert.equal(o.firstTouchClosedAt,null);
  assert.equal(o.gates.midpointTouch,'INSUFFICIENT_DATA');
  assert.equal(o.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(o.eligibleForLiveTrading,false);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`an unclosed ${direction} successor cannot expose a missing middle wait hour`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const prefix=studyHourlyFvgMidpointAsOf(bars,source,25*H);
  // Hour 24 is absent. Hour 25 has not closed at the 25H boundary.
  // Its data accessors must not be read, even to diagnose a gap.
  const forbidden=()=>{throw Error('unclosed future candle was inspected');};
  const future={
   time:25*H,
   get open(){return forbidden() as number;},
   get high(){return forbidden() as number;},
   get low(){return forbidden() as number;},
   get close(){return forbidden() as number;},
   get volume(){return forbidden() as number;},
   get observed_minutes(){return forbidden() as number;},
  } as Bar;
  const asOf=studyHourlyFvgMidpointAsOf([...bars,future],source,25*H);
  const pick=(result:typeof prefix)=>result.observations.find(
   o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.deepEqual(pick(asOf),pick(prefix));
  assert.equal(pick(asOf)?.firstTouchCensorReason,'RIGHT_CENSORED');
  assert.equal(pick(asOf)?.firstTouchClosedAt,null);
  assert.equal(pick(asOf)?.eligibleForLiveTrading,false);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`a still-later completed ${direction} midpoint wick cannot erase an earlier missing middle hour`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   {time:25*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   {time:26*H,open:104,high:105,low:100,close:104,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   {time:25*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   {time:26*H,open:96,high:102,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const first=studyHourlyFvgMidpointAsOf(bars.slice(0,-1),source,26*H);
  const later=studyHourlyFvgMidpointAsOf(bars,source,27*H);
  const pick=(r:typeof first)=>r.observations.find(
   o=>o.direction===direction&&o.formationClosedAt===23*H);
  const before=pick(first),after=pick(later);
  assert.ok(before);
  assert.ok(after);
  assert.equal(before.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(after.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(after.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(after.firstTouchCensorMissingHourSlots,1);
  // The later wick cannot retroactively expand the observed pre-gap risk set
  // or move the time at which the missing slot first became observable.
  assert.equal(after.firstTouchObservedWaitBars,1);
  assert.equal(after.firstTouchCensorObservedAt,26*H);
  assert.equal(after.firstTouchClosedAt,null);
  assert.equal(after.gates.midpointTouch,'INSUFFICIENT_DATA');
  assert.equal(after.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(after.eligibleForLiveTrading,false);
 });
}
