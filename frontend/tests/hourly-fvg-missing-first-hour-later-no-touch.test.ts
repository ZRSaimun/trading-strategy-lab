import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID-only archive. A later no-touch candle cannot resolve an earlier
// unobserved first-eligible hour; it is not evidence of an uninterrupted wait.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`missing first-eligible hour remains censored after a later ${direction} non-touch close`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const formed=studyHourlyFvgMidpointAsOf(bars,source,23*H);
  const baseline=formed.observations.find(o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.ok(baseline);
  assert.equal(baseline.firstTouchCensorReason,'RIGHT_CENSORED');
  // Hour 23 is absent. Hour 24 closes without touching the midpoint.
  const later:Bar=bullish?
   {time:24*H,open:104,high:105,low:103,close:104,volume:999,observed_minutes:60}:
   {time:24*H,open:96,high:97,low:95,close:96,volume:999,observed_minutes:60};
  const result=studyHourlyFvgMidpointAsOf([...bars,later],source,25*H);
  const observation=result.observations.find(o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.ok(observation);
  assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(observation.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(observation.firstTouchCensorMissingHourSlots,1);
  assert.equal(observation.firstTouchCensorObservedAt,25*H);
  assert.equal(observation.firstTouchClosedAt,null);
  assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
  assert.equal(observation.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(observation.eligibleForLiveTrading,false);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`unclosed future ${direction} candle cannot resolve missing first hour or execute price getters`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  // Hour 23 is missing; hour 24 is not closed at the 24H boundary.
  const future={time:24*H} as Bar;
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(future,field,{enumerable:true,get(){throw new Error(`future ${field} accessed`);}});
  }
  const baseline=studyHourlyFvgMidpointAsOf(bars,source,24*H);
  const extended=studyHourlyFvgMidpointAsOf([...bars,future],source,24*H);
  const select=(result:typeof baseline)=>result.observations.find(
   o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.deepEqual(select(extended),select(baseline));
  assert.equal(select(extended)?.firstTouchCensorReason,'RIGHT_CENSORED');
  assert.equal(select(extended)?.eligibleForLiveTrading,false);
 });
}
