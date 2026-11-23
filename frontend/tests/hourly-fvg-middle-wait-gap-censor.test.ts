import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// All prices are synthetic BID-only fixtures, not executable broker quotations.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`a later ${direction} midpoint wick cannot resolve a missing *middle* wait hour`,()=>{
  const bullish=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bullish?100:101,high:bullish?101:102,
   low:bullish?99:100,close:bullish?100:101,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(bullish?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   // First eligible wait hour (23) is complete and does not touch.
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   // Hour 24 missing; hour 25 touches the bullish gap midpoint (~101).
   {time:25*H,open:104,high:105,low:100,close:103,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   // Hour 24 missing; hour 25 touches bearish gap midpoint (~100).
   {time:25*H,open:96,high:101,low:95,close:97,volume:10,observed_minutes:60},
  ]));
  const before=studyHourlyFvgMidpointAsOf(bars.slice(0,-1),source,24*H);
  const after=studyHourlyFvgMidpointAsOf(bars,source,26*H);
  const pick=(result:typeof before)=>result.observations.find(
   o=>o.direction===direction&&o.formationClosedAt===23*H);
  assert.equal(pick(before)?.firstTouchCensorReason,'RIGHT_CENSORED');
  const observation=pick(after);
  assert.ok(observation);
  assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(observation.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(observation.firstTouchCensorMissingHourSlots,1);
  assert.equal(observation.firstTouchCensorObservedAt,26*H);
  assert.equal(observation.firstTouchClosedAt,null);
  assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
  assert.equal(observation.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(observation.eligibleForLiveTrading,false);
 });
}
